#!/usr/bin/env python3
"""Account for every frozen cell and attempt; report each criteria label separately, without readiness claims."""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any

import pilot_ledger as ledger


def planned_cells(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = manifest['matrix']
    return [{'scenario': s, 'condition': c, 'run': r, 'cell': f'{s}/{c}/run-{r}',
                 'criteria': manifest['scorer']['criteria_by_scenario'][s]}
            for r in range(1, matrix['runs'] + 1) for s in matrix['scenarios'] for c in matrix['conditions']]


def attempts_for(root: Path) -> list[Path]:
    return sorted((p for p in root.glob('attempt-*') if p.is_dir() and re.fullmatch(r'attempt-\d+(?:-retry|-resume)?', p.name)),
                  key=lambda p: int(p.name.split('-')[1]))


def original_stage1(stage: Path, root: Path, cell: str) -> Path:
    """Follow copied-evidence references to the single invocation that produced the handoff."""
    seen = set()
    stage = stage.resolve()
    while True:
        if stage in seen:
            raise ValueError('cycle in restored stage-1 provenance')
        seen.add(stage)
        parts = stage.relative_to(root.resolve()).parts
        if len(parts) != 5 or parts[-1] != 'stage1' or '/'.join(parts[1:4]) != cell:
            raise ValueError('restored stage-1 provenance does not name the same pilot cell')
        mapping = root / parts[0] / 'STAGE1_RECOVERY.json'
        source = json.loads(mapping.read_text()).get(cell) if mapping.exists() else None
        if not source:
            return stage
        stage = Path(source).resolve()


def ledger_index(root: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    entries = ledger.read_ledger(root / 'LEDGER.jsonl')
    completed = {e.get('session_id') for e in entries if e.get('event') == 'session'}
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        if entry.get('event') not in ('session', 'session_start') or not entry.get('out_dir'):
            continue
        if entry['event'] == 'session_start' and entry['session_id'] in completed:
            continue
        try:
            attempt = Path(entry['out_dir']).resolve().relative_to(root.resolve()).parts[0]
        except (ValueError, IndexError):
            raise ValueError('ledger session path is outside its pilot directory') from None
        index.setdefault((attempt, entry['cell']), []).append(entry)
    for attempt in attempts_for(root):
        mapping = attempt / 'STAGE1_RECOVERY.json'
        if not mapping.exists():
            continue
        for cell, source in json.loads(mapping.read_text()).items():
            original = original_stage1(Path(source), root, cell)
            inherited = [e for e in entries if e.get('event') == 'session' and e.get('kind') == 'stage1'
                         and e.get('out_dir') and Path(e['out_dir']).resolve() == original and e.get('cell') == cell]
            index.setdefault((attempt.name, cell), []).extend(dict(e, reused_evidence=True) for e in inherited)
    return index


def validate_score(payload: dict[str, Any], cell: dict[str, Any]) -> str | None:
    if payload.get('criteria_version') != cell['criteria']:
        return 'score criteria differ from the frozen scenario criteria'
    for key in ('scenario', 'condition', 'run'):
        if type(payload.get(key)) is not type(cell[key]) or payload.get(key) != cell[key]:
            return f'score {key} is absent or differs from the frozen cell identity'
    if type(payload.get('pass')) is not bool:
        return 'score pass is missing or is not a boolean'
    assertions = payload.get('assertions')
    if not isinstance(assertions, dict) or not assertions or any(type(v) is not bool for v in assertions.values()):
        return 'score assertions must be nonempty booleans'
    if payload['pass'] != all(assertions.values()) or payload.get('failed_assertions') != [k for k, v in assertions.items() if not v]:
        return 'score contradicts its assertions'
    if assertions.get('hidden_runner_completed') is False:
        return 'scoring instrument failed; rescore preserved output before evaluating outcomes'
    return None


def classify_attempt(attempt: Path, cell: dict[str, Any], sessions: list[dict[str, Any]]) -> dict[str, Any]:
    root = attempt / cell['cell']
    info: dict[str, Any] = {'attempt': attempt.name, 'path': str(root), 'cell': cell['cell'], 'sessions': len(sessions)}
    if not root.exists() and not sessions:
        return dict(info, status='not_attempted')
    if any(s.get('event') == 'session_start' for s in sessions):
        return dict(info, status='interrupted_unknown', reason='session reserved but result not captured; manual disposition required')
    # A completed first session is real B3 work. Re-running the cell would repeat it even if
    # stage 2 never connected. Until stage-aware recovery establishes the preserved stage-1
    # snapshot, stop for offline/manual recovery instead of admitting a full-cell resume.
    if cell['scenario'] == 'b3' and not (root / 'run.json').exists() and not (root / 'run.recovered.json').exists():
        handoff = root / 'stage1'
        score_path = handoff / 'run-stage1.json'
        stage2 = [s for s in sessions if s.get('kind') == 'stage2']
        if score_path.exists() and (handoff / 'SNAPSHOT.json').is_file() and (handoff / 'repo-snapshot').is_dir() and stage2:
            handoff_score = json.loads(score_path.read_text())
            last = stage2[-1]
            if (handoff_score.get('criteria_version') == cell['criteria'] and handoff_score.get('pass') is True
                    and last.get('has_agent_work') is False and (last.get('provider_limit') or last.get('infrastructure_failure'))):
                return dict(info, status='stage2_paused' if last.get('provider_limit') and not last.get('model_mismatch') else 'stage2_infrastructure',
                            stage1_recovery=str(original_stage1(handoff, attempt.parent, cell['cell'])))
        for part in ('stage2', 'stage1'):
            transcript = root / part / 'transcript.jsonl'
            if transcript.exists():
                parsed = ledger.parse_session(transcript, transcript.parent / 'stderr.txt')
                if parsed['has_result'] and parsed['result_success'] and (root / 'repo').is_dir():
                    return dict(info, status='unscored_recoverable', recoverable_transcript=str(transcript))
    if any(s.get('model_mismatch') for s in sessions):
        return dict(info, status='infrastructure_failure', reason='known model mismatch overrides later provider limit')
    limited = [s for s in sessions if s.get('provider_limit')]
    if limited:
        return dict(info, status='provider_limit_interrupted', provider_limit=limited[-1].get('provider_limit_detail'))
    if any(s.get('infrastructure_failure') for s in sessions):
        return dict(info, status='infrastructure_failure')
    for name, status in (('run.json', 'scored'), ('run.recovered.json', 'recovered_conditional')):
        path = root / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
            problem = validate_score(payload, cell)
        except (ValueError, TypeError, AttributeError) as exc:
            problem = f'invalid score: {exc}'
        if problem:
            return dict(info, status='invalid_score', reason=problem, file=name)
        if status == 'scored':
            kinds = ('stage1', 'stage2') if cell['scenario'] == 'b3' else ('main',)
            if any(sum(s.get('kind') == kind and s.get('event') == 'session' and s.get('rc') is not None
                       and not s.get('model_unknown') and not s.get('model_mismatch') for s in sessions) != 1 for kind in kinds):
                return dict(info, status='invalid_score', reason='score lacks exactly one recorded execution for each required stage', file=name)
        return dict(info, status=status, file=name, **{'pass': payload['pass']})
    # B3 preserves two sessions; either complete stage requires recovery before any rerun.
    transcripts = [root / part / 'transcript.jsonl' for part in ('session', 'stage2', 'stage1')]
    for transcript in transcripts:
        if not transcript.exists():
            continue
        parsed = ledger.parse_session(transcript, transcript.parent / 'stderr.txt')
        if parsed['has_result'] and parsed['result_success'] and (root / 'repo').is_dir():
            return dict(info, status='unscored_recoverable', recoverable_transcript=str(transcript))
        return dict(info, status='interrupted_unknown', reason='unscored partial transcript requires manual disposition')
    if sessions:
        return dict(info, status='interrupted_unknown', reason='recorded session has no recoverable output')
    return dict(info, status='unstarted')


def resolve(planned: list[dict[str, Any]], root: Path, retry_limit: int) -> list[dict[str, Any]]:
    attempts, index = attempts_for(root), ledger_index(root)
    rows = []
    for cell in planned:
        history = [classify_attempt(a, cell, index.get((a.name, cell['cell']), [])) for a in attempts]
        history = [h for h in history if h['status'] != 'not_attempted']
        scored = [h for h in history if h['status'] == 'scored']
        recovered = [h for h in history if h['status'] == 'recovered_conditional']
        failed = [h for h in history if h['status'] in ('infrastructure_failure', 'stage2_infrastructure')]
        retries = sum(h['attempt'].endswith('-retry') for h in history)
        used = scored[0] if scored else recovered[0] if recovered else None
        reasons = []
        if len(scored) > 1:
            reasons.append('multiple ordinary scores; preserve the first and investigate the unauthorized rerun')
        if retries > retry_limit:
            reasons.append('retry allowance exceeded')
        if any(h['status'] == 'invalid_score' for h in history):
            reasons.append('invalid score identity or criteria')
        if used and any(h['status'] in ('unscored_recoverable', 'recovered_conditional', 'interrupted_unknown')
                        for h in history[:history.index(used)]):
            reasons.append('rerun after existing model work instead of recovering or adjudicating it')
        if used:
            status = used['status']
        elif any(h['status'] == 'unscored_recoverable' for h in history):
            status = 'unscored_recoverable'
        elif any(h['status'] in ('invalid_score', 'interrupted_unknown') for h in history):
            status = 'review_required'
        elif failed:
            status = 'excluded_infrastructure'
        elif any(h['status'] in ('provider_limit_interrupted', 'stage2_paused') for h in history):
            status = 'paused_provider_limit'
        else:
            status = 'missing'
        rows.append(dict(cell, attempts=history, used=used, status=status, retries_used=retries,
                         retry_authorized=retries <= retry_limit, execution_deviations=reasons,
                         stage1_recovery=next((h['stage1_recovery'] for h in reversed(history) if h.get('stage1_recovery')), None),
                         **{'pass': used['pass'] if used else None}))
    return rows


def load_used(rows: list[dict[str, Any]], ordinary_only: bool = False) -> list[dict[str, Any]]:
    cells = []
    for row in rows:
        used = row['used']
        if not used or (ordinary_only and row['status'] != 'scored'):
            continue
        payload = json.loads((Path(used['path']) / used['file']).read_text())
        cells.append(dict(payload, _cell=row['cell'], _conditional=row['status'] == 'recovered_conditional'))
    return cells


def number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def paired_measure(rows: list[dict[str, Any]], reference: str, treatment: str, key: str) -> dict[str, Any]:
    expected = {(r['scenario'], r['run']) for r in rows if r['condition'] in (reference, treatment)}
    cells = load_used(rows, ordinary_only=True)
    index = {(c['scenario'], c['condition'], c['run']): c for c in cells}
    ratios = []
    for scenario, run in expected:
        left = index.get((scenario, reference, run), {}).get(key)
        right = index.get((scenario, treatment, run), {}).get(key)
        if number(left) and number(right) and left > 0:
            ratios.append(right / left)
    complete = bool(expected) and len(ratios) == len(expected) and not any(r['execution_deviations'] for r in rows)
    return {'n_pairs_planned': len(expected), 'n_pairs_with_data': len(ratios), 'complete': complete,
                'status': 'COMPLETE' if complete else 'INSUFFICIENT_EVIDENCE',
                'median_paired_ratio': statistics.median(ratios) if complete else None,
                'preliminary_median_paired_ratio': statistics.median(ratios) if ratios and not complete else None}


def analyse(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    rows = resolve(planned_cells(manifest), root, manifest['budget']['policy']['retries_per_cell'])
    arms = manifest['matrix']['conditions']
    complete = bool(rows) and all(r['status'] == 'scored' and not r['execution_deviations'] for r in rows)
    entries = ledger.read_ledger(root / 'LEDGER.jsonl')
    accounting_issues = []
    if any(bool(e.get('mock')) != bool(manifest.get('offline_mock_only')) for e in entries if e.get('event') == 'session'):
        accounting_issues.append('mock/live session evidence differs from frozen mode')
    if not manifest.get('offline_mock_only'):
        for arm in ('forge', 'candidate'):
            if not any(e.get('event') == 'session' and e.get('kind') == 'preflight' and e.get('cell') == f'{arm}-activation'
                       and e.get('rc') == 0 and e.get('result_success') and not e.get('model_mismatch') and not e.get('model_unknown') for e in entries):
                accounting_issues.append(f'{arm} activation has no verified recorded session')
    if accounting_issues:
        complete = False
    planned_paths = {r['cell'] for r in rows}
    unexpected = [str(p) for a in attempts_for(root) for p in a.glob('*/*/run-*/run*.json')
                  if str(p.parent.relative_to(a)) not in planned_paths]
    if unexpected:
        complete = False
    labels = sorted({r['criteria'] for r in rows})
    by_label = {}
    for label in labels:
        selected = [r for r in rows if r['criteria'] == label]
        scenarios = sorted({r['scenario'] for r in selected})
        stats = {}
        for scenario in scenarios:
            sr = [r for r in selected if r['scenario'] == scenario]
            stats[scenario] = {
                'arms': {arm: {
                    'planned': sum(r['condition'] == arm for r in sr),
                    'scored': sum(r['condition'] == arm and r['status'] == 'scored' for r in sr),
                    'passes': sum(r['condition'] == arm and r['status'] == 'scored' and r['pass'] for r in sr),
                    'conditional_recoveries': sum(r['condition'] == arm and r['status'] == 'recovered_conditional' for r in sr),
                } for arm in arms},
                'pairings': {f'{treatment}_vs_{reference}': {
                    key: paired_measure(sr, reference, treatment, key) for key in ('tokens_total', 'wall_seconds')
                } for i, reference in enumerate(arms) for treatment in arms[i + 1:]},
            }
        if accounting_issues or unexpected:
            for scenario_stats in stats.values():
                for pairing in scenario_stats['pairings'].values():
                    for measure in pairing.values():
                        if measure['complete']:
                            measure['preliminary_median_paired_ratio'] = measure['median_paired_ratio']
                        measure.update(complete=False, status='INSUFFICIENT_EVIDENCE', median_paired_ratio=None)
        by_label[label] = {'complete': not accounting_issues and not unexpected and all(r['status'] == 'scored' and not r['execution_deviations'] for r in selected), 'scenarios': stats}
    cells = load_used(rows)
    reviews = [c['_cell'] for c in cells if any(
        c.get(key, {}).get('status') == 'review_required' for key in ('scope_review', 'state_accuracy', 'process_review'))]
    reviews += [c['_cell'] for c in cells if c['_cell'] not in reviews and any(
        d.get('status') == 'review_required' for d in c.get('dimensions', {}).values() if isinstance(d, dict))]
    counts = {s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})}
    return {'matrix_status': 'COMPLETE' if complete else 'INSUFFICIENT_EVIDENCE', 'planned': len(rows), 'counts': counts,
                'by_criteria': by_label, 'cells': rows, 'unexpected_scores': unexpected, 'accounting_issues': accounting_issues,
                'accounting': ledger.totals(ledger.read_ledger(root / 'LEDGER.jsonl')), 'semantic_review_pending': reviews,
                'mock': bool(manifest.get('offline_mock_only')), 'readiness': 'NOT_ASSESSED', 'note': 'Automated checks and descriptive comparisons only. Criteria labels are never pooled. '
                'Conditional recovered scores are reported separately and do not complete primary comparisons. Human review and '
                'statistical interpretation are required; no quality, adoption, or zero-overhead claim follows automatically.'}


def write_report(result: dict[str, Any], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    lines = ['# Frozen pilot accounting', '', f"Matrix: **{result['matrix_status']}**; planned cells: {result['planned']}.", '', result['note'], '']
    for label, data in result['by_criteria'].items():
        lines += [f'## Criteria {label}', '', '| Scenario | Arm | Planned | Scored | Passes | Conditional recoveries |', '|---|---|---:|---:|---:|---:|']
        for scenario, stats in data['scenarios'].items():
            for arm, values in stats['arms'].items():
                lines.append(f"| {scenario} | {arm} | {values['planned']} | {values['scored']} | {values['passes']} | {values['conditional_recoveries']} |")
        lines += ['', 'Pairings and missing-evidence counts are in the accompanying JSON. Ratios are median within-scenario paired ratios.', '']
    lines += [f"Semantic reviews pending: {len(result['semantic_review_pending'])}. Readiness: **NOT_ASSESSED**.", '']
    out.with_suffix('.md').write_text('\n'.join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--pilot-dir', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()
    result = analyse(json.loads(Path(args.manifest).read_text()), Path(args.pilot_dir))
    out = Path(args.out) if args.out else Path(args.pilot_dir) / 'ANALYSIS.json'
    write_report(result, out)
    print(f"{result['matrix_status']}; readiness NOT_ASSESSED; {out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
