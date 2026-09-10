"""Offline regression tests for frozen pilot identity, crash accounting, recovery and unbiased attempt selection."""
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'evals/core'
sys.path.insert(0, str(CORE))
ledger = importlib.import_module('pilot_ledger')
launch = importlib.import_module('pilot_launch')
analysis = importlib.import_module('pilot_analysis')
manifest_mod = importlib.import_module('pilot_manifest')


def transcript(path: Path, *, model: str | None = 'pinned-model', cost: float | None = None, error: str | None = None, result: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [{'type': 'system', 'subtype': 'init', 'model': model}]
    if result:
        events.append({'type': 'result', 'subtype': 'error' if error else 'success', 'is_error': bool(error),
                       'result': error or 'done', 'total_cost_usd': cost, 'usage': {'input_tokens': 1, 'output_tokens': 2}})
    path.write_text('\n'.join(json.dumps(e) for e in events) + '\n')
    return path


def score(root: Path, cell: dict, *, passed: bool = True, tokens: float | None = 100, conditional: bool = False) -> Path:
    path = root / cell['cell'] / ('run.recovered.json' if conditional else 'run.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: cell[k] for k in ('scenario', 'condition', 'run')}
    payload.update(criteria_version=cell['criteria'], **{'pass': passed}, assertions={'correctness': passed},
                   failed_assertions=[] if passed else ['correctness'], tokens_total=tokens, wall_seconds=10,
                   state_accuracy={'status': 'review_required'})
    path.write_text(json.dumps(payload))
    if root.name.startswith('attempt-'):
        session = path.parent / 'session'
        t = transcript(session / 'transcript.jsonl')
        ledger.record(root.parent / 'LEDGER.jsonl', 'main', cell['cell'], t, 0, None, 0.0, session)
    return path


@pytest.fixture
def frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, Path, Path]:
    harness = tmp_path / 'harness'
    shutil.copytree(CORE, harness / 'evals/core', ignore=shutil.ignore_patterns('__pycache__'))
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    (candidate / 'SKILL.md').write_text('Candidate instructions\n')
    (candidate / 'VERSION').write_text('1.11.0\n')
    monkeypatch.setattr(launch, 'git', lambda root, *args: '' if args[0] == 'status' else 'frozen-head')
    monkeypatch.setattr(manifest_mod, 'release_identity', lambda *args: ('release-head', 'release-projection'))
    args = argparse.Namespace(harness=str(harness), candidate_dir=str(candidate), scenarios=['b4', 'q4'], runs=1, seed=7,
        invocation_ceiling=20, retries_per_cell=1, usd_ceiling=None, reserve_usd=None, forge_release='v1.11.0', no_images=True,
        runtime='docker', agent_image='agent:test', scorer_image='scorer:test', network_image='proxy:test', model='pinned-model',
        max_turns=80, agent_timeout=2400, scorer_timeout=60)
    manifest, order = manifest_mod.build(args)
    specdir = tmp_path / 'frozen'
    specdir.mkdir()
    path = specdir / 'pilot_manifest.json'
    path.write_text(json.dumps(manifest))
    (specdir / 'RUN_ORDER.frozen.tsv').write_text(order)
    return manifest, path, tmp_path / 'pilot'


def test_atomic_reservation_counts_crashes_and_prevents_duplicate_dispatch(tmp_path: Path) -> None:
    path = tmp_path / 'ledger.jsonl'
    out = tmp_path / 'session'
    assert ledger.start(path, 1, 'main', 'b4/forge/run-1', out)[0]
    assert not ledger.start(path, 2, 'main', 'b4/forge/run-1', out)[0]
    totals = ledger.totals(ledger.read_ledger(path))
    assert totals['sessions'] == totals['pending_sessions'] == totals['unknown_usage_sessions'] == 1
    assert not ledger.check(path, 1)[0]
    t = transcript(out / 'transcript.jsonl', cost=0.5)
    first = ledger.record(path, 'main', 'b4/forge/run-1', t, 0, 'pinned-model', None, out)
    assert ledger.record(path, 'main', 'b4/forge/run-1', t, 0, 'pinned-model', None, out) == first
    totals = ledger.totals(ledger.read_ledger(path))
    assert totals['sessions'] == 1 and totals['pending_sessions'] == 0


def test_atomic_ceiling_cannot_be_raced(tmp_path: Path) -> None:
    path = tmp_path / 'ledger.jsonl'
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda n: ledger.start(path, 1, 'main', f'b4/forge/run-{n}', tmp_path / f'session-{n}')[0], range(6)))
    assert sum(results) == 1
    assert ledger.totals(ledger.read_ledger(path))['sessions'] == 1


def test_unknown_usage_reserve_is_optional_and_never_zero_under_estimate_policy(tmp_path: Path) -> None:
    path = tmp_path / 'ledger.jsonl'
    ledger.start(path, 5, 'main', 'b4/forge/run-1', tmp_path / 'session')
    assert ledger.check(path, 5)[0]
    ok, verdict = ledger.check(path, 5, usd_ceiling=1.0, reserve=0.6)
    assert not ok and verdict['committed_usd_if_started'] == 1.2
    for cost in (float('nan'), float('inf'), -1, True):
        parsed = ledger.parse_session(transcript(tmp_path / 'badcost.jsonl', cost=cost))
        assert parsed['cost_usd'] is None
    with pytest.raises(ValueError, match='every started'):
        ledger.check(path, 5, exclude_unreachable=True)


@pytest.mark.parametrize('message,kind', [('You hit your limit; resetsAtSeconds 2000000000', 'subscription'),
    ('API Error: Unable to connect to API: certificate verify failed', 'unreachable'), ('OAuth session expired; please run /login', 'auth')])
def test_subscription_and_connection_failures_pause_but_still_count(tmp_path: Path, message: str, kind: str) -> None:
    t = transcript(tmp_path / 'session/transcript.jsonl', error=message)
    e = ledger.record(tmp_path / 'ledger.jsonl', 'main', 'b4/forge/run-1', t, 1, 'pinned-model', None, t.parent)
    assert e['provider_limit_detail']['kind'] == kind
    assert not e['infrastructure_failure']
    assert ledger.totals(ledger.read_ledger(tmp_path / 'ledger.jsonl'))['sessions'] == 1


def test_model_identity_is_required_and_successful_text_does_not_trigger_pause(tmp_path: Path) -> None:
    t = transcript(tmp_path / 'session/transcript.jsonl', model=None)
    e = ledger.record(tmp_path / 'ledger.jsonl', 'main', 'b4/forge/run-1', t, 0, 'pinned-model', None, t.parent)
    assert e['model_unknown'] and e['infrastructure_failure']
    t = transcript(tmp_path / 'success/transcript.jsonl')
    t.write_text(t.read_text().replace('done', 'Tests cover error 429 and authentication_error'))
    assert ledger.parse_session(t)['provider_limit'] is None


def test_reconcile_preserves_unknown_exit_and_does_not_double_count_reservation(tmp_path: Path) -> None:
    root = tmp_path / 'pilot'
    out = root / 'attempt-1/b4/forge/run-1/session'
    ledger_path = root / 'LEDGER.jsonl'
    ledger.start(ledger_path, 10, 'main', 'b4/forge/run-1', out)
    transcript(out / 'transcript.jsonl', cost=0.8)
    assert len(ledger.reconcile(ledger_path, root, 'pinned-model')['repaired']) == 1
    assert ledger.reconcile(ledger_path, root, 'pinned-model')['repaired'] == []
    entries = ledger.read_ledger(ledger_path)
    assert entries[-1]['rc'] is None and entries[-1]['repaired']
    assert ledger.totals(entries)['sessions'] == 1


def test_manifest_is_subscription_first_and_freezes_every_declared_scenario(frozen) -> None:
    manifest, _, _ = frozen
    assert manifest['matrix']['cells'] == 6 and manifest['budget']['planned_invocations'] == 8
    assert manifest['budget']['policy']['billing'] == 'subscription-only'
    assert manifest['budget']['policy']['usd_ceiling'] is None
    assert manifest['scorer']['criteria_by_scenario'] == {'b4': 'v4', 'q4': 'v4-supp1'}
    assert launch.verify(manifest, True, 'docker') == []
    assert launch.verify(manifest, False, 'missing-runtime')


def test_verify_rejects_candidate_source_hidden_test_and_frozen_order_changes(frozen) -> None:
    manifest, path, root = frozen
    candidate = Path(manifest['candidate']['worktree']) / 'SKILL.md'
    original = candidate.read_text()
    candidate.write_text(original + 'Changed')
    assert any('candidate' in p for p in launch.verify(manifest, True, 'docker'))
    candidate.write_text(original)
    hidden = next((Path(manifest['harness']['root']) / 'evals/core/hidden').rglob('*.py'))
    hidden.write_text(hidden.read_text() + '\n# changed\n')
    assert any('source' in p for p in launch.verify(manifest, True, 'docker'))
    root.mkdir()
    path.with_name('RUN_ORDER.frozen.tsv').write_text('changed')
    with pytest.raises(ValueError, match='order'):
        launch.bind_manifest(manifest, root, path)


def test_live_controls_cannot_inherit_test_overrides(frozen, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, _, _ = frozen
    monkeypatch.setenv('BENCH_AGENT_RUN_EXTRA_ARGS', '--network=host')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-only-placeholder')
    problems = launch.verify(manifest, True, 'docker')
    assert any('BENCH_AGENT_RUN_EXTRA_ARGS' in p for p in problems)
    assert any('ANTHROPIC_API_KEY' in p for p in problems)


def test_manifest_binding_refuses_post_start_amendment(frozen) -> None:
    manifest, path, root = frozen
    root.mkdir()
    launch.bind_manifest(manifest, root, path)
    manifest['budget']['policy']['invocation_ceiling'] += 100
    with pytest.raises(ValueError, match='different frozen'):
        launch.bind_manifest(manifest, root, path)


def test_partial_and_mixed_criteria_never_yield_complete_comparisons(frozen) -> None:
    manifest, _, root = frozen
    cells = analysis.planned_cells(manifest)
    score(root / 'attempt-1', cells[0])
    result = analysis.analyse(manifest, root)
    assert result['matrix_status'] == 'INSUFFICIENT_EVIDENCE' and result['readiness'] == 'NOT_ASSESSED'
    assert set(result['by_criteria']) == {'v4', 'v4-supp1'}
    ratio = result['by_criteria']['v4']['scenarios']['b4']['pairings']['candidate_vs_baseline']['tokens_total']
    assert ratio['status'] == 'INSUFFICIENT_EVIDENCE' and ratio['median_paired_ratio'] is None
    assert result['semantic_review_pending'] == [cells[0]['cell']]
    path = score(root / 'attempt-1', cells[1])
    data = json.loads(path.read_text()); data['criteria_version'] = 'v3.1'; path.write_text(json.dumps(data))
    result = analysis.analyse(manifest, root)
    assert result['matrix_status'] == 'INSUFFICIENT_EVIDENCE'
    assert result['cells'][1]['execution_deviations']


def test_complete_three_arm_matrix_reports_without_adoption_claim(frozen) -> None:
    manifest, _, root = frozen
    for cell in analysis.planned_cells(manifest):
        score(root / 'attempt-1', cell, tokens=100 if cell['condition'] == 'baseline' else 150)
    result = analysis.analyse(manifest, root)
    assert result['matrix_status'] == 'COMPLETE' and result['readiness'] == 'NOT_ASSESSED'
    assert result['by_criteria']['v4']['scenarios']['b4']['pairings']['candidate_vs_baseline']['tokens_total']['median_paired_ratio'] == 1.5
    analysis.write_report(result, root / 'ANALYSIS.json')
    assert 'Criteria v4-supp1' in (root / 'ANALYSIS.md').read_text()
    assert len(result['semantic_review_pending']) == 6


def test_first_outcome_is_not_replaced_by_later_success(frozen) -> None:
    manifest, _, root = frozen
    cell = analysis.planned_cells(manifest)[0]
    score(root / 'attempt-1', cell, passed=False)
    score(root / 'attempt-2-retry', cell)
    result = analysis.resolve([cell], root, 1)[0]
    assert result['pass'] is False and result['execution_deviations']


def test_recoverable_work_blocks_resume_and_conditional_scores_stay_separate(frozen) -> None:
    manifest, _, root = frozen
    cell = analysis.planned_cells(manifest)[0]
    folder = root / 'attempt-1' / cell['cell']
    (folder / 'repo').mkdir(parents=True)
    transcript(folder / 'session/transcript.jsonl')
    row = analysis.resolve([cell], root, 1)[0]
    assert row['status'] == 'unscored_recoverable'
    assert cell['cell'] not in launch.unscored_cells(manifest, root)
    score(root / 'attempt-1', cell, conditional=True)
    row = analysis.resolve([cell], root, 1)[0]
    assert row['status'] == 'recovered_conditional'
    assert analysis.analyse(manifest, root)['matrix_status'] == 'INSUFFICIENT_EVIDENCE'


def test_pending_start_without_transcript_cannot_be_automatically_rerun(frozen) -> None:
    manifest, _, root = frozen
    cell = analysis.planned_cells(manifest)[0]
    ledger.start(root / 'LEDGER.jsonl', 10, 'main', cell['cell'], root / 'attempt-1' / cell['cell'] / 'session')
    (root / 'attempt-1').mkdir()
    assert analysis.resolve([cell], root, 1)[0]['status'] == 'review_required'
    assert cell['cell'] not in launch.unscored_cells(manifest, root)


def test_b3_recovery_refuses_to_invent_missing_stage_snapshot(tmp_path: Path) -> None:
    row = {'scenario': 'b3', 'cell': 'b3/forge/run-1', 'attempts': [{'status': 'unscored_recoverable', 'path': str(tmp_path)}]}
    result = launch.recover_cell({}, tmp_path, row, True, 'docker')
    assert result['status'] == 'manual_recovery_required'


def test_offline_recovery_uses_supported_scorer_arguments(frozen, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, _, root = frozen
    cell = analysis.planned_cells(manifest)[0]
    folder = root / 'attempt-1' / cell['cell']
    (folder / 'repo').mkdir(parents=True)
    t = transcript(folder / 'session/transcript.jsonl')
    row = analysis.resolve([cell], root, 1)[0]
    manifest['scorer']['image_id'] = 'sha256:mock'
    payload_path = score(root / 'fixture', cell)
    payload = json.loads(payload_path.read_text())
    commands = []
    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), '')
    monkeypatch.setattr(launch.subprocess, 'run', fake_run)
    result = launch.recover_cell(manifest, root, row, False, 'fake-docker')
    assert result['status'] == 'recovered_conditional'
    assert '--fixture-version' not in commands[0] and commands[0][commands[0].index('--network') + 1] == 'none'
    assert str(t) + ':/evidence/transcript.jsonl:ro' in commands[0]
    recovered = json.loads((folder / 'run.recovered.json').read_text())
    assert recovered['recovery']['actual_rc'] is None and recovered['recovery']['assumed_rc_for_scoring'] == 0
    assert recovered['wall_seconds'] is None


def test_launcher_excludes_provider_pauses_from_retry_allowance(frozen, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, path, root = frozen
    root.mkdir()
    launch.bind_manifest(manifest, root, path)
    cell = analysis.planned_cells(manifest)[0]
    folder = root / 'attempt-1' / cell['cell'] / 'session'
    t = transcript(folder / 'transcript.jsonl', error='You hit your limit')
    ledger.record(root / 'LEDGER.jsonl', 'main', cell['cell'], t, 1, 'pinned-model', None, folder)
    row = analysis.resolve([cell], root, 1)[0]
    assert row['status'] == 'paused_provider_limit' and row['retries_used'] == 0
    assert cell['cell'] in launch.unscored_cells(manifest, root)
    args = argparse.Namespace(command='retry', manifest=str(path), pilot_dir=str(root), runtime='docker', mock='reference')
    started = []
    monkeypatch.setattr(launch, 'run_harness', lambda *a: started.append(a) or 0)
    assert launch.command_execute(args, manifest) == 0 and started == []


def test_b3_successful_stage_is_recovered_before_resuming_a_provider_pause(frozen) -> None:
    manifest, _, root = frozen
    manifest['matrix']['scenarios'] = ['b3']
    manifest['scorer']['criteria_by_scenario'] = {'b3': 'v4'}
    cell = analysis.planned_cells(manifest)[0]
    folder = root / 'attempt-1' / cell['cell']
    (folder / 'repo').mkdir(parents=True)
    transcript(folder / 'stage1/transcript.jsonl')
    t = transcript(folder / 'stage2/transcript.jsonl', error='Unable to connect to API')
    ledger.record(root / 'LEDGER.jsonl', 'stage2', cell['cell'], t, 1, 'pinned-model', None, t.parent)
    assert analysis.resolve([cell], root, 1)[0]['status'] == 'unscored_recoverable'
    assert cell['cell'] not in launch.unscored_cells(manifest, root)


def test_real_preflight_layout_is_reconciled_with_original_identity(tmp_path: Path) -> None:
    root = tmp_path / 'pilot'
    out = root / 'attempt-1/forge-activation-preflight'
    ledger.start(root / 'LEDGER.jsonl', 10, 'preflight', 'forge-activation', out)
    transcript(out / 'transcript.jsonl')
    ledger.reconcile(root / 'LEDGER.jsonl', root, 'pinned-model')
    totals = ledger.totals(ledger.read_ledger(root / 'LEDGER.jsonl'))
    assert totals['sessions'] == 1 and totals['pending_sessions'] == 0


@pytest.mark.parametrize('model,rc,expected', [('wrong-model', 0, 6), (None, 0, 6), (None, 124, 0)])
def test_cli_record_stops_wrong_model_but_timeout_remains_outcome(tmp_path: Path, model, rc: int, expected: int) -> None:
    t = transcript(tmp_path / 'session/transcript.jsonl', model=model, result=rc != 124)
    result = subprocess.run([sys.executable, str(CORE / 'pilot_ledger.py'), 'record', '--ledger', str(tmp_path / 'LEDGER.jsonl'),
        '--kind', 'main', '--cell', 'b4/forge/run-1', '--out-dir', str(t.parent), '--transcript', str(t), '--rc', str(rc),
        '--pinned-model', 'pinned-model'], capture_output=True, text=True, check=False)
    assert result.returncode == expected
    assert ledger.totals(ledger.read_ledger(tmp_path / 'LEDGER.jsonl'))['sessions'] == 1


def test_launcher_passes_the_verified_container_runtime(frozen, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, path, root = frozen
    root.mkdir()
    args = argparse.Namespace(command='run', manifest=str(path), pilot_dir=str(root), runtime='chosen-runtime', mock='reference')
    manifest['harness']['runtime'] = 'chosen-runtime'
    envs = []
    monkeypatch.setattr(launch, 'run_harness', lambda manifest, out, env, log: envs.append(env) or 0)
    assert launch.command_execute(args, manifest) == 0
    assert envs[0]['BENCH_CONTAINER_RUNTIME'] == 'chosen-runtime'


def test_response_model_overrides_requested_init_and_subagents_do_not_mask_mismatch(tmp_path: Path) -> None:
    t = transcript(tmp_path / 'session/transcript.jsonl')
    events = [json.loads(line) for line in t.read_text().splitlines()]
    events.insert(1, {'type': 'assistant', 'parent_tool_use_id': None, 'message': {'model': 'different-main-model', 'content': []}})
    events.insert(2, {'type': 'assistant', 'parent_tool_use_id': 'side-task', 'message': {'model': 'pinned-model', 'content': []}})
    t.write_text('\n'.join(json.dumps(e) for e in events))
    e = ledger.record(tmp_path / 'LEDGER.jsonl', 'main', 'b4/forge/run-1', t, 0, 'pinned-model', None, t.parent)
    assert e['main_model'] == 'different-main-model' and e['model_mismatch'] and e['infrastructure_failure']
    assert e['init_model'] == 'pinned-model'


def test_b3_zero_work_stage2_resumes_from_frozen_stage1_snapshot(frozen) -> None:
    manifest, _, root = frozen
    manifest['matrix']['scenarios'] = ['b3']
    manifest['scorer']['criteria_by_scenario'] = {'b3': 'v4'}
    cell = analysis.planned_cells(manifest)[0]
    folder = root / 'attempt-1' / cell['cell']
    (folder / 'repo').mkdir(parents=True)
    stage1 = folder / 'stage1'
    transcript(stage1 / 'transcript.jsonl')
    (stage1 / 'repo-snapshot').mkdir()
    (stage1 / 'SNAPSHOT.json').write_text('{}')
    (stage1 / 'run-stage1.json').write_text(json.dumps({'criteria_version': 'v4', 'pass': True}))
    t = transcript(folder / 'stage2/transcript.jsonl', error='Unable to connect to API')
    events = [json.loads(line) for line in t.read_text().splitlines()]
    events[-1]['usage'] = {'input_tokens': 0, 'output_tokens': 0}
    t.write_text('\n'.join(json.dumps(e) for e in events))
    ledger.record(root / 'LEDGER.jsonl', 'stage2', cell['cell'], t, 1, 'pinned-model', None, t.parent)
    row = analysis.resolve([cell], root, 1)[0]
    assert row['status'] == 'paused_provider_limit' and row['stage1_recovery'] == str(stage1)
    assert cell['cell'] in launch.unscored_cells(manifest, root)
    # A late limit after agent work is never eligible for the zero-work path.
    entries = ledger.read_ledger(root / 'LEDGER.jsonl')
    entries[-1]['model_mismatch'] = True
    (root / 'LEDGER.jsonl').write_text('\n'.join(json.dumps(e) for e in entries))
    assert analysis.resolve([cell], root, 1)[0]['status'] == 'excluded_infrastructure'
    entries[-1]['model_mismatch'] = False
    entries[-1]['has_agent_work'] = True
    (root / 'LEDGER.jsonl').write_text('\n'.join(json.dumps(e) for e in entries))
    assert analysis.resolve([cell], root, 1)[0]['status'] == 'unscored_recoverable'


def test_launcher_forwards_sigterm_to_child_group_and_waits_for_cleanup(tmp_path: Path) -> None:
    import os
    import signal
    import time
    core = tmp_path / 'harness/evals/core'
    core.mkdir(parents=True)
    ready, cleaned = tmp_path / 'ready', tmp_path / 'cleaned'
    script = core / 'run.sh'
    script.write_text('trap \'wait "$kid" 2>/dev/null; printf cleaned > "$CLEANED"; exit 143\' TERM INT\nsleep 60 &\nkid=$!\nprintf ready > "$READY"\nwait "$kid"\n')
    command = [sys.executable, '-c', ('import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import pilot_launch; '
        'm={"matrix":{"scenarios":["b4"],"conditions":["baseline"],"runs":1},"harness":{"root":sys.argv[2]}}; '
        'raise SystemExit(pilot_launch.run_harness(m,Path(sys.argv[3]),dict(__import__("os").environ),Path(sys.argv[4])))'),
        str(CORE), str(tmp_path / 'harness'), str(tmp_path / 'out'), str(tmp_path / 'log')]
    proc = subprocess.Popen(command, env={**os.environ, 'READY': str(ready), 'CLEANED': str(cleaned)})
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=5) == 143
        assert cleaned.read_text() == 'cleaned'
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_score_without_execution_accounting_does_not_complete_matrix(frozen) -> None:
    manifest, _, root = frozen
    for cell in analysis.planned_cells(manifest):
        score(root / 'attempt-1', cell)
    (root / 'LEDGER.jsonl').unlink()
    result = analysis.analyse(manifest, root)
    assert result['matrix_status'] == 'INSUFFICIENT_EVIDENCE'
    assert all(r['status'] == 'review_required' for r in result['cells'])


def test_copied_stage1_transcript_does_not_count_as_another_invocation(tmp_path: Path) -> None:
    root = tmp_path / 'pilot'
    original = root / 'attempt-1/b3/forge/run-1/stage1'
    t = transcript(original / 'transcript.jsonl')
    ledger.record(root / 'LEDGER.jsonl', 'stage1', 'b3/forge/run-1', t, 0, 'pinned-model', None, original)
    copied = root / 'attempt-2-resume/b3/forge/run-1/stage1'
    copied.mkdir(parents=True)
    shutil.copy2(t, copied / 'transcript.jsonl')
    (root / 'attempt-2-resume/STAGE1_RECOVERY.json').write_text(json.dumps({'b3/forge/run-1': str(original)}))
    assert ledger.reconcile(root / 'LEDGER.jsonl', root, 'pinned-model')['repaired'] == []
    assert ledger.totals(ledger.read_ledger(root / 'LEDGER.jsonl'))['sessions'] == 1
    index = analysis.ledger_index(root)
    assert index[('attempt-2-resume', 'b3/forge/run-1')][0]['reused_evidence']
    third = root / 'attempt-3-resume/b3/forge/run-1/stage1'
    third.mkdir(parents=True)
    shutil.copy2(t, third / 'transcript.jsonl')
    (root / 'attempt-3-resume/STAGE1_RECOVERY.json').write_text(json.dumps({'b3/forge/run-1': str(copied)}))
    assert ledger.reconcile(root / 'LEDGER.jsonl', root, 'pinned-model')['repaired'] == []
    index = analysis.ledger_index(root)
    assert index[('attempt-3-resume', 'b3/forge/run-1')][0]['out_dir'] == str(original)
    assert analysis.original_stage1(third, root, 'b3/forge/run-1') == original


def test_cleanup_removes_only_known_config_credentials_without_following_symlink(tmp_path: Path) -> None:
    root = tmp_path / 'pilot'
    config = root / 'attempt-1/b4/forge/run-1/config'
    config.mkdir(parents=True)
    credential = config / '.credentials.json'
    credential.write_text('synthetic secret')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / '.credentials.json').write_text('must remain')
    (config.parent / 'stage1-config').symlink_to(outside, target_is_directory=True)
    repo = config.parent / 'repo'
    repo.mkdir()
    (repo / '.credentials.json').write_text('candidate fixture file must remain')
    launch.cleanup_cache({}, root)
    assert not credential.exists()
    assert (outside / '.credentials.json').read_text() == 'must remain'
    assert (repo / '.credentials.json').exists()


def test_known_model_mismatch_dominates_later_provider_limit(tmp_path: Path) -> None:
    t = transcript(tmp_path / 'session/transcript.jsonl', model='wrong-model', error='You hit your limit')
    result = subprocess.run([sys.executable, str(CORE / 'pilot_ledger.py'), 'record', '--ledger', str(tmp_path / 'LEDGER.jsonl'),
        '--kind', 'main', '--cell', 'b4/forge/run-1', '--out-dir', str(t.parent), '--transcript', str(t), '--rc', '1',
        '--pinned-model', 'pinned-model'], capture_output=True, text=True, check=False)
    assert result.returncode == 6
    assert ledger.read_ledger(tmp_path / 'LEDGER.jsonl')[-1]['infrastructure_failure']
