#!/usr/bin/env python3
"""Verify, run, pause/resume, explicitly retry infrastructure failures, recover offline, and report a frozen pilot.

Live `run` and `resume` return on subscription/auth/network limits; they never silently switch credentials,
models or billing. Complete model output is recovered before rerunning anything. `--mock` is restricted to
manifests frozen with --no-images; synthetic local scoring is never admitted as live evidence.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pilot_analysis as analysis
import pilot_ledger as ledger

SCORER_ITEMS = ['assert_run.py', 'score_entrypoint.py', 'fixture_bundle.py', 'fixture_bundle.json.gz.b64', 'fixture_supplements.json', 'hidden']
SCORER_SOURCES = [*SCORER_ITEMS, 'container/ScorerContainerfile']
TEST_ONLY_ENV = ('BENCH_SCORER_LOCAL', 'BENCH_MOCK_INFRA_FAIL', 'BENCH_MOCK_AGENT', 'BENCH_CONFIG_SEED_DIR',
                 'BENCH_AGENT_RUN_EXTRA_ARGS', 'PERMISSION_FLAGS', 'BENCH_CEILING_EXCLUDES_UNREACHABLE', 'FORGE_DIR', 'ALLOW_UNVERIFIED_FORGE', 'FORGE_REPO')


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_file(path: Path) -> bool:
    return path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo')


def projection_sha256(root: Path, items: list[str]) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    for item in items:
        base = root / item
        paths = sorted(p for p in base.rglob('*') if content_file(p)) if base.is_dir() else [base] if content_file(base) else []
        for path in paths:
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
                raise ValueError(f'symlinked frozen input is unsupported: {path}')
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b'\0')
            digest.update(path.read_bytes())
            digest.update(b'\0')
    return digest.hexdigest()


def scorer_source_sha256(core: Path) -> str:
    return projection_sha256(core, SCORER_SOURCES)


def run_order_text(scenarios: list[str], conditions: list[str], runs: int, seed: int) -> str:
    rng = random.Random(seed)
    lines = ['ordinal\trun\tscenario\tcondition']
    ordinal = 0
    for run in range(1, runs + 1):
        shuffled = scenarios[:]
        rng.shuffle(shuffled)
        for scenario in shuffled:
            arms = conditions[:]
            rng.shuffle(arms)
            for condition in arms:
                ordinal += 1
                lines.append(f'{ordinal}\t{run}\t{scenario}\t{condition}')
    return '\n'.join(lines) + '\n'


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def image_id(runtime: str, image: str) -> str | None:
    result = subprocess.run([runtime, 'image', 'inspect', image, '--format', '{{.Id}}'], capture_output=True, text=True, check=False, timeout=30)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip().startswith('sha256:') else None


def require_image(runtime: str, image: str) -> str:
    resolved = image_id(runtime, image)
    if not resolved:
        raise ValueError(f'image is absent or its identity cannot be resolved: {image}')
    return resolved


def network_identity(core: Path, runtime: str, image: str) -> dict[str, Any]:
    completed = subprocess.run([sys.executable, str(core / 'network_run.py'), 'identity', runtime, image],
                               capture_output=True, text=True, check=True, timeout=60)
    return json.loads(completed.stdout)


def scorer_image_hash(core: Path, runtime: str, image: str) -> str:
    # Compare actual immutable image contents with checkout sources, not only an unrelated image tag.
    code = f"""import hashlib,pathlib
root=pathlib.Path('/scorer'); digest=hashlib.sha256()
for item in {SCORER_ITEMS!r}:
 base=root/item
 paths=sorted(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo')) if base.is_dir() else [base] if base.is_file() else []
 for p in paths:
  digest.update(p.relative_to(root).as_posix().encode()); digest.update(b'\\0'); digest.update(p.read_bytes()); digest.update(b'\\0')
print(digest.hexdigest())
"""
    result = subprocess.run([runtime, 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                             '--security-opt', 'no-new-privileges', '--entrypoint', 'python3', image, '-c', code],
                            capture_output=True, text=True, check=True, timeout=60)
    return result.stdout.strip()


def verify(manifest: dict[str, Any], mock: bool, runtime: str) -> list[str]:
    problems = []
    try:
        if manifest.get('schema_version') != 1 or bool(manifest.get('offline_mock_only')) != mock:
            problems.append('manifest mode/schema mismatch: offline mock and live identities cannot be mixed')
        if manifest['harness']['runtime'] != runtime:
            problems.append('container runtime differs from frozen selection')
        harness = Path(manifest['harness']['root'])
        core = harness / 'evals/core'
        if git(harness, 'rev-parse', 'HEAD') != manifest['harness']['commit']:
            problems.append('harness commit differs from frozen identity')
        if git(harness, 'status', '--porcelain', '--untracked-files=no'):
            problems.append('harness tracked working tree has uncommitted changes')
        if projection_sha256(harness, ['evals/core']) != manifest['harness']['source_sha256']:
            problems.append('harness source bytes differ from frozen identity')
        candidate = manifest['candidate']
        root = Path(candidate['worktree'])
        if projection_sha256(root, candidate['runtime_items']) != candidate['runtime_projection_sha256']:
            problems.append('candidate runtime projection differs from frozen identity')
        if sha256_bytes((root / 'SKILL.md').read_bytes()) != candidate['skill_md_sha256'] or (root / 'VERSION').read_text().strip() != candidate['version']:
            problems.append('candidate SKILL.md or VERSION differs from frozen identity')
        if scorer_source_sha256(core) != manifest['scorer']['source_sha256']:
            problems.append('scorer source differs from frozen identity')
        if sha256_bytes((core / 'fixture_bundle.json.gz.b64').read_bytes()) != manifest['scorer']['fixture_bundle_sha256']:
            problems.append('fixture bundle differs from frozen identity')
        inputs = subprocess.run([sys.executable, '-c', ('import json; from assert_run import SCENARIO_CRITERIA; '
            'from fixture_bundle import load_bundle; print(json.dumps({"criteria":SCENARIO_CRITERIA,"prompts":load_bundle()["prompts"]}))')],
            cwd=core, capture_output=True, text=True, check=True)
        actual = json.loads(inputs.stdout)
        matrix = manifest['matrix']
        if matrix['conditions'] != ['baseline', 'forge', 'candidate'] or matrix['runs'] < 1 or len(set(matrix['scenarios'])) != len(matrix['scenarios']):
            problems.append('invalid frozen three-arm matrix')
        if {s: actual['criteria'].get(s) for s in matrix['scenarios']} != manifest['scorer']['criteria_by_scenario']:
            problems.append('scenario criteria differ from frozen mapping')
        prompts = {k: sha256_bytes(v.encode()) for k, v in actual['prompts'].items() if k.split('-')[0] in matrix['scenarios']}
        if prompts != manifest['prompts_sha256']:
            problems.append('task prompts differ from frozen mapping')
        order = run_order_text(matrix['scenarios'], matrix['conditions'], matrix['runs'], matrix['seed'])
        if sha256_bytes(order.encode()) != matrix['run_order_sha256']:
            problems.append('regenerated order differs from frozen order identity')
        if not manifest['harness']['model'] or manifest['budget']['policy']['ceiling_counts'] != 'all':
            problems.append('pinned model and counting every started invocation are required')
        if not mock:
            if require_image(runtime, manifest['harness']['agent_image']) != manifest['harness']['agent_image_id']:
                problems.append('agent image identity differs')
            if require_image(runtime, manifest['scorer']['image']) != manifest['scorer']['image_id']:
                problems.append('scorer image identity differs')
            if scorer_image_hash(core, runtime, manifest['scorer']['image_id']) != projection_sha256(core, SCORER_ITEMS):
                problems.append('actual scorer image sources differ from frozen checkout')
            if network_identity(core, runtime, manifest['network']['image']) != manifest['network']['identity']:
                problems.append('network boundary image, policy or sources differ')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        problems.append(f'frozen identity verification failed: {exc}')
    for name in TEST_ONLY_ENV:
        if os.environ.get(name):
            problems.append(f'environment override {name} is forbidden; use explicit --mock for offline validation')
    if os.environ.get('ANTHROPIC_API_KEY'):
        problems.append('ANTHROPIC_API_KEY must be unset; the pilot uses subscription credentials')
    return problems


def controls_env(manifest: dict[str, Any], root: Path, mock: str | None, cells: list[str] | None) -> dict[str, str]:
    matrix, harness, policy = manifest['matrix'], manifest['harness'], manifest['budget']['policy']
    # Do not inherit unlisted BENCH knobs from an earlier run. Credential source is the only operator input.
    env = {k: v for k, v in os.environ.items() if not k.startswith('BENCH_') and k not in ('ANTHROPIC_API_KEY', 'CANDIDATE_DIR', 'FORGE_REF', 'FORGE_DIR', 'ALLOW_UNVERIFIED_FORGE', 'FORGE_REPO')}
    env.update(PATH=str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', ''), BENCH_SEED=str(matrix['seed']),
        BENCH_AGENT_IMAGE=harness['agent_image'], BENCH_SCORER_IMAGE=manifest['scorer']['image'], CLAUDE_MODEL=harness['model'],
        MAX_TURNS=str(harness['max_turns']), AGENT_TIMEOUT=str(harness['agent_timeout_s']), SCORER_TIMEOUT=str(harness['scorer_timeout_s']),
        FORGE_INVOCATION=harness['forge_invocation'], BENCH_LEDGER=str(root / 'LEDGER.jsonl'), BENCH_INVOCATION_CEILING=str(policy['invocation_ceiling']),
        BENCH_PINNED_MODEL=harness['model'], BENCH_EXPECT_RUN_ORDER_SHA256=matrix['run_order_sha256'],
        CANDIDATE_DIR=manifest['candidate']['worktree'], FORGE_REF=manifest['forge_arm']['release'])
    if policy['usd_ceiling'] is not None:
        env.update(BENCH_USD_CEILING=str(policy['usd_ceiling']), BENCH_SESSION_RESERVE_USD=str(policy['per_session_reserve_usd']))
    if mock:
        env['BENCH_MOCK_AGENT'] = mock
    else:
        identity = manifest['network']['identity']
        env.update(COPY_CREDENTIALS='1', BENCH_EXPECT_AGENT_IMAGE_ID=harness['agent_image_id'],
            BENCH_EXPECT_SCORER_IMAGE_ID=manifest['scorer']['image_id'], BENCH_EXPECT_CANDIDATE_SHA256=manifest['candidate']['runtime_projection_sha256'],
            BENCH_EXPECT_FORGE_SHA256=manifest['forge_arm']['runtime_projection_sha256'],
            BENCH_NETWORK_IMAGE=manifest['network']['image'], BENCH_EXPECT_NETWORK_IMAGE_ID=identity['proxy_image_id'],
            BENCH_EXPECT_NETWORK_IDENTITY_SHA256=identity['network_identity_sha256'])
        if os.environ.get('BENCH_CREDENTIALS_FILE'):
            env['BENCH_CREDENTIALS_FILE'] = os.environ['BENCH_CREDENTIALS_FILE']
        env['BENCH_CREDENTIAL_CACHE_DIR'] = str(credential_cache(manifest, root))
    if cells is not None:
        env['BENCH_CELL_FILTER'] = ' '.join(cells)
    return env


def credential_cache(manifest: dict[str, Any], root: Path) -> Path:
    state = root / 'CREDENTIAL_CACHE.json'
    source = Path(os.environ.get('BENCH_CREDENTIALS_FILE', str(Path.home() / '.claude/.credentials.json'))).resolve()
    if state.exists():
        saved = json.loads(state.read_text())
        cache = Path(saved['path'])
        if saved['source'] != str(source) or not cache.is_dir() or cache.is_symlink():
            raise ValueError('private credential cache/source changed; restore it before resuming')
    else:
        cache = Path(tempfile.mkdtemp(prefix='forge-pilot-credentials-'))
        os.chmod(cache, 0o700)
        state.write_text(json.dumps({'path': str(cache), 'source': str(source)}) + '\n')
        state.chmod(0o600)
    helper = Path(manifest['harness']['root']) / 'evals/core/credential_cache.py'
    subprocess.run([sys.executable, str(helper), 'init', str(source), str(cache)], check=True)
    return cache


def reconcile_or_fail(manifest: dict[str, Any], root: Path) -> None:
    if analysis.attempts_for(root):
        ledger.reconcile(root / 'LEDGER.jsonl', root, manifest['harness']['model'])


def bind_manifest(manifest: dict[str, Any], root: Path, source: Path) -> None:
    frozen = root / 'FROZEN_MANIFEST.json'
    order = source.parent / manifest['matrix']['run_order_file']
    if not order.is_file() or sha256_bytes(order.read_bytes()) != manifest['matrix']['run_order_sha256']:
        raise ValueError('frozen run-order file is absent or was edited')
    if frozen.exists():
        if json.loads(frozen.read_text()) != manifest:
            raise ValueError('pilot is already bound to different frozen inputs; use a new pilot directory')
    else:
        if analysis.attempts_for(root) or (root / 'LEDGER.jsonl').exists():
            raise ValueError('existing unbound pilot artifacts cannot be adopted into a new manifest')
        frozen.write_text(json.dumps(manifest, indent=2) + '\n')


def record_attempt(root: Path, entry: dict[str, Any]) -> None:
    ledger.append(root / 'ATTEMPTS.jsonl', dict(recorded_utc=datetime.now(timezone.utc).isoformat(), **entry))


def next_attempt_dir(root: Path, retry: bool, resume: bool = False) -> Path:
    attempts = analysis.attempts_for(root)
    n = max((int(p.name.split('-')[1]) for p in attempts), default=0) + 1
    return root / f"attempt-{n}{'-retry' if retry else '-resume' if resume else ''}"


def unscored_cells(manifest: dict[str, Any], root: Path) -> list[str]:
    rows = analysis.resolve(analysis.planned_cells(manifest), root, manifest['budget']['policy']['retries_per_cell'])
    return [r['cell'] for r in rows if r['status'] in ('missing', 'paused_provider_limit')]


def run_harness(manifest: dict[str, Any], out: Path, env: dict[str, str], log: Path) -> int:
    matrix = manifest['matrix']
    core = Path(manifest['harness']['root']) / 'evals/core'
    command = ['bash', str(core / 'run.sh'), '--scenarios', ','.join(matrix['scenarios']), '--conditions', ','.join(matrix['conditions']),
               '--runs', str(matrix['runs']), '--out', str(out)]
    with log.open('w') as stream:
        process = subprocess.Popen(command, cwd=core, env=env, stdin=subprocess.DEVNULL, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        interrupted = [None, None]
        def forward(signum, frame):
            interrupted[:] = [signum, time.monotonic() + 10]
            try:
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                pass
        original = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            while True:
                try:
                    rc = process.wait(timeout=0.2)
                    return 128 + interrupted[0] if interrupted[0] else rc
                except subprocess.TimeoutExpired:
                    if interrupted[1] is not None and time.monotonic() >= interrupted[1]:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=5)
                        return 128 + interrupted[0]
        finally:
            for sig, handler in original.items():
                signal.signal(sig, handler)



def command_execute(args: argparse.Namespace, manifest: dict[str, Any]) -> int:
    root = Path(args.pilot_dir).resolve()
    problems = verify(manifest, bool(args.mock), args.runtime)
    if problems:
        print('\n'.join('MISMATCH: ' + p for p in problems), file=sys.stderr)
        return 2
    bind_manifest(manifest, root, Path(args.manifest))
    reconcile_or_fail(manifest, root)
    attempts = analysis.attempts_for(root)
    if args.command == 'run' and attempts:
        raise ValueError('pilot has existing attempts; use resume, recover, or an explicit infrastructure retry')
    if args.command != 'run' and not attempts:
        raise ValueError('no attempt exists; use run')
    rows = analysis.resolve(analysis.planned_cells(manifest), root, manifest['budget']['policy']['retries_per_cell'])
    if any(r['status'] == 'unscored_recoverable' for r in rows):
        raise ValueError('complete model work awaits offline recovery; run recover before any new session')
    if any(r['status'] == 'review_required' or r['execution_deviations'] for r in rows):
        raise ValueError('unknown/invalid execution evidence requires manual disposition; no new session started')
    if args.command == 'retry':
        limit = manifest['budget']['policy']['retries_per_cell']
        cells = [r['cell'] for r in rows if r['status'] == 'excluded_infrastructure' and r['retries_used'] < limit]
    else:
        cells = None if args.command == 'run' else unscored_cells(manifest, root)
    if cells == []:
        print('No eligible cells. Complete existing evidence and inspect the report; no session started.')
        return 0
    out = next_attempt_dir(root, retry=args.command == 'retry', resume=args.command == 'resume')
    out.mkdir()
    record_attempt(root, {'event': 'start', 'command': args.command, 'attempt': out.name, 'cells': cells, 'mock': args.mock})
    env = controls_env(manifest, root, args.mock, cells)
    recoveries = {r['cell']: r['stage1_recovery'] for r in rows if r.get('stage1_recovery') and cells is not None and r['cell'] in cells}
    if recoveries:
        recovery_file = out / 'STAGE1_RECOVERY.json'
        recovery_file.write_text(json.dumps(recoveries, indent=2) + '\n')
        env['BENCH_STAGE1_RECOVERY'] = str(recovery_file)
    env['BENCH_CONTAINER_RUNTIME'] = args.runtime
    rc = run_harness(manifest, out, env, root / f'{out.name}.log')
    record_attempt(root, {'event': 'finish', 'command': args.command, 'attempt': out.name, 'rc': rc, 'mock': args.mock})
    if rc == 4 and (out / 'PAUSED.json').exists():
        print(f'PAUSED: progress retained in {out}; resolve the reported limit, then explicitly resume with the same manifest.')
    else:
        print(f'{out.name} finished rc={rc}; progress retained; no adoption conclusion.')
    if not args.mock and analysis.analyse(manifest, root)['matrix_status'] == 'COMPLETE':
        cleanup_cache(manifest, root)
    return rc


def cleanup_cache(manifest: dict[str, Any], root: Path) -> None:
    for attempt in analysis.attempts_for(root):
        configs = [p / name for p in attempt.glob('*/*/run-*') for name in ('config', 'stage1-config', 'stage2-config')]
        configs += [attempt / f'{arm}-activation-preflight/config' for arm in ('forge', 'candidate')]
        for config in configs:
            if any(p.is_symlink() for p in (config, *config.parents) if p != root.parent):
                continue
            credential = config / '.credentials.json'
            if credential.exists() or credential.is_symlink():
                credential.unlink()
    state = root / 'CREDENTIAL_CACHE.json'
    if not state.exists():
        return
    cache = Path(json.loads(state.read_text())['path'])
    if cache.is_symlink() or not cache.name.startswith('forge-pilot-credentials-') or cache.parent.resolve() != Path(tempfile.gettempdir()).resolve():
        raise ValueError('refusing cleanup outside the dedicated temporary credential cache')
    helper = Path(manifest['harness']['root']) / 'evals/core/credential_cache.py'
    subprocess.run([sys.executable, str(helper), 'cleanup', str(cache)], check=True)
    state.unlink()


def recover_cell(manifest: dict[str, Any], root: Path, row: dict[str, Any], mock: bool, runtime: str) -> dict[str, Any]:
    prior = next(h for h in row['attempts'] if h['status'] == 'unscored_recoverable')
    cell_dir = Path(prior['path'])
    if row['scenario'] == 'b3':
        return {'cell': row['cell'], 'status': 'manual_recovery_required', 'reason': 'two-stage recovery must establish the stage-1 snapshot and verdict; never rerun blindly'}
    transcript = Path(prior['recoverable_transcript'])
    session = next((s for s in ledger.read_ledger(root / 'LEDGER.jsonl') if s.get('event') == 'session' and s.get('transcript') == str(transcript.resolve())), {})
    rc = session.get('rc')
    note = {'actual_rc': rc, 'assumed_rc_for_scoring': 0 if rc is None else None, 'wall_seconds': None,
                'note': 'Preserved successful transcript scored offline. Unknown process exit code is explicitly assumed zero; '
                     'conditional recovery never completes primary comparisons. No provider invocation.'}
    meta = {'scenario': row['scenario'], 'condition': row['condition'], 'run': row['run'], 'rc': 0 if rc is None else rc,
                'mock': mock, 'timed_out': False, 'wall_seconds': None, 'fixture_version': manifest['scorer']['fixture_version'],
                'criteria_version': row['criteria'], 'evidence': {'repo': str(cell_dir / 'repo'), 'transcript': str(transcript)}}
    meta_path = cell_dir / 'meta.recovered-scoring.json'
    meta_path.write_text(json.dumps(meta, indent=2) + '\n')
    (cell_dir / 'meta.recovered.json').write_text(json.dumps(dict(meta, rc=rc, recovery=note), indent=2) + '\n')
    out = cell_dir / 'run.recovered.json'
    if out.exists():
        return {'cell': row['cell'], 'status': 'already_recovered', 'path': str(out)}
    core = Path(manifest['harness']['root']) / 'evals/core'
    if mock:
        command = [sys.executable, str(core / 'assert_run.py'), '--phase', 'final', '--scenario', row['scenario'], '--repo', str(cell_dir / 'repo'),
                   '--meta', str(meta_path), '--transcript', str(transcript), '--out', str(out)]
    else:
        command = [sys.executable, str(core / 'container_run.py'), runtime, str(manifest['harness']['scorer_timeout_s']), '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                   '--pids-limit', '128', '--memory', '768m', '--cpus', '1', '--tmpfs', '/work:rw,nosuid,nodev,size=512m,mode=1777',
                   '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m,mode=1777', '-e', 'HOME=/tmp/scorer-home', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                   '-e', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', '-v', f'{cell_dir / "repo"}:/input:ro', '-v', f'{meta_path}:/evidence/meta.json:ro',
                   '-v', f'{transcript}:/evidence/transcript.jsonl:ro', manifest['scorer']['image_id'], 'python3', '/scorer/score_entrypoint.py',
                   '--phase', 'final', '--scenario', row['scenario'], '--meta', '/evidence/meta.json', '--transcript', '/evidence/transcript.jsonl']
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=manifest['harness']['scorer_timeout_s'] + 45)
    (cell_dir / 'recovery-scorer.log').write_text(result.stderr)
    if result.returncode:
        return {'cell': row['cell'], 'status': 'recovery_failed', 'rc': result.returncode}
    payload = json.loads(out.read_text() if mock else result.stdout)
    problem = analysis.validate_score(payload, row)
    if problem:
        raise ValueError('recovered score rejected: ' + problem)
    payload.update(recovery=note, wall_seconds=None)
    out.write_text(json.dumps(payload, indent=2) + '\n')
    return dict(cell=row['cell'], status='recovered_conditional', path=str(out), **{'pass': payload['pass']})


@contextlib.contextmanager
def pilot_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.launcher.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another launcher owns this pilot; concurrent attempts are refused') from None
        yield


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify', 'run', 'resume', 'retry', 'recover', 'report', 'cleanup'))
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--pilot-dir', required=True)
    parser.add_argument('--runtime', default='docker')
    parser.add_argument('--mock', choices=('reference', 'noop', 'drifter'))
    args = parser.parse_args()
    manifest, root = json.loads(Path(args.manifest).read_text()), Path(args.pilot_dir).resolve()
    try:
        if args.command == 'verify':
            problems = verify(manifest, bool(args.mock), args.runtime)
            order = Path(args.manifest).parent / manifest['matrix']['run_order_file']
            if not order.exists() or sha256_bytes(order.read_bytes()) != manifest['matrix']['run_order_sha256']:
                problems.append('frozen order file absent or altered')
            print('\n'.join('MISMATCH: ' + p for p in problems) if problems else 'VERIFIED: frozen identities match; no provider session started')
            return 2 if problems else 0
        with pilot_lock(root):
            if args.command in ('run', 'resume', 'retry'):
                return command_execute(args, manifest)
            if args.command == 'cleanup':
                cleanup_cache(manifest, root)
                print('Private cache and known harness credential copies removed; results and original source retained.')
                return 0
            bind_manifest(manifest, root, Path(args.manifest))
            reconcile_or_fail(manifest, root)
            if args.command == 'recover':
                problems = verify(manifest, bool(args.mock), args.runtime)
                if problems:
                    raise ValueError('; '.join(problems))
                rows = analysis.resolve(analysis.planned_cells(manifest), root, manifest['budget']['policy']['retries_per_cell'])
                results = [recover_cell(manifest, root, r, bool(args.mock), args.runtime) for r in rows if r['status'] == 'unscored_recoverable']
                for result in results:
                    print(json.dumps(result))
                return 2 if any(r['status'] in ('manual_recovery_required', 'recovery_failed') for r in results) else 0
            result = analysis.analyse(manifest, root)
            analysis.write_report(result, root / 'ANALYSIS.json')
            print(f"{result['matrix_status']}; readiness NOT_ASSESSED; {root / 'ANALYSIS.json'}")
            return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f'Pilot stopped: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
