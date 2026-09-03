#!/usr/bin/env python3
"""SessionStart hook: inject a concise execution-control orientation.

Copy/adapt to .claude/hooks/session-start-control.py and configure for
startup|resume|clear|compact. Non-blocking by design.
"""
import json, subprocess, sys
from pathlib import Path

try: inp=json.load(sys.stdin)
except Exception: inp={}
root=Path(inp.get("cwd") or ".")
control=root/".claude"/"project-control.json"
if not control.exists(): sys.exit(0)
try: d=json.loads(control.read_text(encoding="utf-8"))
except Exception as e:
    msg=f"EXECUTION CONTROL WARNING: cannot parse {control}: {e}. Reconcile control state before substantive implementation."
else:
    validation="not checked"
    validator=root/".claude"/"control"/"validate-project-control.py"
    if validator.exists():
        p=subprocess.run([sys.executable,str(validator),str(control)],capture_output=True,text=True)
        validation="valid" if p.returncode==0 else "INVALID: "+(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "validator failed")
    active_m=", ".join(d.get("active_milestones",[])) or "none"
    active_w=", ".join(d.get("active_work_packets",[])) or "none"
    resume=", ".join(d.get("resume_queue",[])) or "none"
    blockers=[wid for wid,w in d.get("work_packets",{}).items() if w.get("status")=="blocked"]
    gates=d.get("gates",{})
    pc=gates.get("plan_consistency",{}).get("status","unknown")
    conv=gates.get("convergence",{}).get("status","unknown")
    msg=("EXECUTION CONTROL ORIENTATION\n"
         f"Baseline: {d.get('baseline_id')} rev {d.get('baseline_revision')}\n"
         f"Plan revision: {d.get('plan_revision')}\n"
         f"Plan consistency: {pc}\n"
         f"Convergence: {conv}\n"
         f"Active milestones: {active_m}\n"
         f"Active work packets: {active_w}\n"
         f"Blocked packets: {', '.join(blockers) or 'none'}\n"
         f"Resume queue: {resume}\n"
         f"Control validation: {validation}\n"
         "Before substantive implementation, load/reconcile the active packet and current plan state. Do not let local work replace the approved roadmap.")

print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":msg}}))
