#!/usr/bin/env python3
"""Freeze portable pilot inputs before execution. No provider sessions are started.

Required image tags must already resolve locally, and --model must name the exact model identity
expected in transcripts. --no-images is only for trusted offline mocks. Subscription usage is the
default: all started invocations count; provider dollar estimates remain informational.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pilot_launch as launch

RUNTIME_ITEMS = ['SKILL.md', 'README.md', 'BOOTSTRAP.md', 'VERSION', 'LICENSE', 'references', 'templates', 'scripts', 'docs/runner.md']
CONDITIONS = ['baseline', 'forge', 'candidate']


def release_identity(harness: Path, release: str) -> tuple[str, str]:
    commit = launch.git(harness, 'rev-parse', '--verify', f'{release}^{{commit}}')
    with tempfile.TemporaryDirectory(prefix='forge-release-freeze-') as temp:
        archive = subprocess.run(['git', '-C', str(harness), 'archive', '--format=tar', commit], capture_output=True, check=True)
        subprocess.run(['tar', '-x', '-C', temp], input=archive.stdout, check=True)
        projection = launch.projection_sha256(Path(temp), RUNTIME_ITEMS)
    return commit, projection


def build(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    harness, candidate = Path(args.harness).resolve(), Path(args.candidate_dir).resolve()
    core = harness / 'evals/core'
    if args.runs < 1 or len(set(args.scenarios)) != len(args.scenarios) or not args.scenarios:
        raise ValueError('positive runs and nonempty unique scenarios required')
    # Run the selected harness imports in a fresh process to avoid a different checkout cached in sys.modules.
    query = subprocess.run([launch.sys.executable, '-c',
        ('import json; from assert_run import SCENARIO_CRITERIA; from fixture_bundle import load_bundle; '
        'print(json.dumps({"criteria":SCENARIO_CRITERIA,"bundle":load_bundle()}))')], cwd=core,
        capture_output=True, text=True, check=True)
    inputs = json.loads(query.stdout)
    criteria = inputs['criteria']
    if any(s not in criteria for s in args.scenarios):
        raise ValueError('unknown scenario')
    bundle = inputs['bundle']
    order = launch.run_order_text(args.scenarios, CONDITIONS, args.runs, args.seed)
    sessions = sum(2 if s == 'b3' else 1 for s in args.scenarios) * len(CONDITIONS) * args.runs
    planned = sessions + 2
    ceiling = args.invocation_ceiling
    if ceiling < planned or args.retries_per_cell < 0:
        raise ValueError(f'invocation ceiling must cover the {planned} planned sessions; retries must be nonnegative')
    if (args.usd_ceiling is None) != (args.reserve_usd is None):
        raise ValueError('specify both --usd-ceiling and --reserve-usd, or neither')
    if args.usd_ceiling is not None and (args.usd_ceiling <= 0 or args.reserve_usd <= 0):
        raise ValueError('estimate ceiling/reserve must be positive')
    commit, forge_hash = release_identity(harness, args.forge_release)
    candidate_hash = launch.projection_sha256(candidate, RUNTIME_ITEMS)
    if candidate_hash == forge_hash and not args.no_images:
        raise ValueError('Forge and candidate runtime content are identical; distinct version strings are not a treatment')
    network = None if args.no_images else launch.network_identity(core, args.runtime, args.network_image)
    manifest = {
        'schema_version': 1, 'generated_utc': datetime.now(timezone.utc).isoformat(), 'offline_mock_only': args.no_images,
        'candidate': {'worktree': str(candidate), 'version': (candidate / 'VERSION').read_text().strip(),
                      'runtime_items': RUNTIME_ITEMS, 'runtime_projection_sha256': candidate_hash,
                      'skill_md_sha256': launch.sha256_bytes((candidate / 'SKILL.md').read_bytes())},
        'forge_arm': {'release': args.forge_release, 'commit': commit, 'runtime_projection_sha256': forge_hash},
        'harness': {'root': str(harness), 'runtime': args.runtime, 'commit': launch.git(harness, 'rev-parse', 'HEAD'),
                    'source_sha256': launch.projection_sha256(harness, ['evals/core']),
                    'agent_image': args.agent_image, 'agent_image_id': None if args.no_images else launch.require_image(args.runtime, args.agent_image),
                    'model': args.model, 'max_turns': args.max_turns, 'agent_timeout_s': args.agent_timeout,
                    'scorer_timeout_s': args.scorer_timeout, 'forge_invocation': 'Use Forge for the following task.'},
        'scorer': {'image': args.scorer_image, 'image_id': None if args.no_images else launch.require_image(args.runtime, args.scorer_image),
                   'source_sha256': launch.scorer_source_sha256(core), 'fixture_version': bundle.get('fixture_version', 'unknown'),
                   'fixture_bundle_sha256': launch.sha256_bytes((core / 'fixture_bundle.json.gz.b64').read_bytes()),
                   'criteria_by_scenario': {s: criteria[s] for s in args.scenarios}},
        'network': {'image': args.network_image, 'identity': network},
        'prompts_sha256': {k: launch.sha256_bytes(v.encode()) for k, v in bundle['prompts'].items() if k.split('-')[0] in args.scenarios},
        'matrix': {'scenarios': args.scenarios, 'conditions': CONDITIONS, 'runs': args.runs, 'seed': args.seed,
                   'cells': len(args.scenarios) * len(CONDITIONS) * args.runs,
                   'run_order_file': 'RUN_ORDER.frozen.tsv', 'run_order_sha256': launch.sha256_bytes(order.encode())},
        'budget': {'planned_invocations': planned, 'policy': {
            'invocation_ceiling': ceiling, 'ceiling_counts': 'all', 'retries_per_cell': args.retries_per_cell,
            'billing': 'subscription-only' if args.usd_ceiling is None else 'estimate-ceiling',
            'usd_ceiling': args.usd_ceiling, 'per_session_reserve_usd': args.reserve_usd,
            'pause': 'preserve attempt and exit on provider/auth/network limit; explicit resume keeps the frozen model, package, criteria and order',
            'estimate_note': 'Provider dollars are informational, not subscription invoices. An explicit estimate ceiling is checked between sessions; '
                             'unknown usage reserves one full allowance and one session may exceed the reserve.'}},
        'interpretation': 'Product comparison unless identical semantic instructions and loading-only differences are independently demonstrated. '
                          'No automatic adoption, effectiveness or zero-overhead conclusion; criteria versions stay separate.',
    }
    return manifest, order


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness', required=True)
    parser.add_argument('--candidate-dir', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--forge-release', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--agent-image', required=True)
    parser.add_argument('--scorer-image', required=True)
    parser.add_argument('--network-image', required=True)
    parser.add_argument('--runtime', default='docker')
    parser.add_argument('--no-images', action='store_true')
    parser.add_argument('--scenarios', nargs='+', default=['b1', 'b2', 'b3', 'b4', 'b4n', 'b4a', 'q4', 's2', 'v1'])
    parser.add_argument('--runs', type=int, default=2)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--invocation-ceiling', type=int, required=True)
    parser.add_argument('--retries-per-cell', type=int, default=1)
    parser.add_argument('--usd-ceiling', type=float)
    parser.add_argument('--reserve-usd', type=float)
    parser.add_argument('--max-turns', type=int, default=80)
    parser.add_argument('--agent-timeout', type=int, default=2400)
    parser.add_argument('--scorer-timeout', type=int, default=1500)
    args = parser.parse_args()
    root = Path(args.out).resolve()
    if (root / 'pilot_manifest.json').exists() or (root / 'RUN_ORDER.frozen.tsv').exists():
        parser.error('frozen files already exist; use a new output directory')
    manifest, order = build(args)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'RUN_ORDER.frozen.tsv').write_text(order)
    (root / 'pilot_manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n')
    print(root / 'pilot_manifest.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
