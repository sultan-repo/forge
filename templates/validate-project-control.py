#!/usr/bin/env python3
"""Validate generic Forge control-state invariants.

Usage:
  python3 validate-project-control.py [.claude/project-control.json]

This validates accounting/structure, not business correctness or requirement truth.
"""
import json, sys
from pathlib import Path

REQ = {"planned","in_progress","satisfied","deferred","rejected","superseded"}
ITEM = {"planned","in_progress","blocked","done","deferred","cancelled","superseded"}
REQ_DISP = {"deferred","rejected","superseded"}
ITEM_DISP = {"deferred","cancelled","superseded"}
GATE = {"pending","passed","passed_with_explicit_gaps","failed","invalidated"}

path = Path(sys.argv[1] if len(sys.argv) > 1 else ".claude/project-control.json")
errors=[]; warnings=[]
try:
    d=json.loads(path.read_text(encoding="utf-8"))
except Exception as e:
    print(f"CONTROL INVALID: cannot read {path}: {e}", file=sys.stderr); sys.exit(2)

def err(x): errors.append(x)
def warn(x): warnings.append(x)

def disposition_ok(obj, label):
    disp=obj.get("disposition")
    if not isinstance(disp, dict): err(f"{label}: terminal scope disposition requires disposition object"); return
    for k in ("reason","plan_delta","authority_level"):
        if not disp.get(k): err(f"{label}: disposition.{k} is required")
    if disp.get("authority_level") == "explicit_approval" and not disp.get("approval_ref"):
        err(f"{label}: explicit approval disposition requires disposition.approval_ref")

if d.get("version") != 3: err("version must be 3")
for k in ("baseline_revision","plan_revision"):
    if not isinstance(d.get(k), int) or d[k] < 1: err(f"{k} must be integer >= 1")
for k in ("active_milestones","active_work_packets","resume_queue","plan_deltas","archived_plan_deltas"):
    if not isinstance(d.get(k), list): err(f"{k} must be an array")
for k in ("requirements","milestones","work_packets","gates"):
    if not isinstance(d.get(k), dict): err(f"{k} must be an object")

reqs=d.get("requirements",{}); ms=d.get("milestones",{}); wps=d.get("work_packets",{})
for rid,r in reqs.items():
    s=r.get("status")
    if s not in REQ: err(f"requirement {rid}: invalid status {s!r}")
    if s in REQ_DISP: disposition_ok(r, f"requirement {rid}")
    m=r.get("milestone")
    if m is not None and m not in ms: err(f"requirement {rid}: unknown milestone {m}")
    for wp in r.get("work_packets",[]):
        if wp not in wps: err(f"requirement {rid}: unknown work packet {wp}")
    if s in {"planned","in_progress"} and not m and not r.get("work_packets"):
        warn(f"requirement {rid}: active/planned requirement has no milestone/work-packet mapping")

for mid,m in ms.items():
    s=m.get("status")
    if s not in ITEM: err(f"milestone {mid}: invalid status {s!r}")
    if s in ITEM_DISP: disposition_ok(m, f"milestone {mid}")
    for rid in m.get("requirements",[]):
        if rid not in reqs: err(f"milestone {mid}: unknown requirement {rid}")

for wid,w in wps.items():
    s=w.get("status")
    if s not in ITEM: err(f"work packet {wid}: invalid status {s!r}")
    if s in ITEM_DISP: disposition_ok(w, f"work packet {wid}")
    parent=w.get("parent")
    if parent not in ms and parent not in wps: err(f"work packet {wid}: unknown parent {parent!r}")
    for rid in w.get("requirements",[]):
        if rid not in reqs: err(f"work packet {wid}: unknown requirement {rid}")
    for dep in w.get("dependencies",[]):
        if dep not in wps and dep not in ms: err(f"work packet {wid}: unknown dependency {dep}")
    rt=w.get("return_to")
    if rt is not None and rt not in wps and rt not in ms: err(f"work packet {wid}: unknown return_to {rt!r}")
    br=w.get("baseline_revision"); pr=w.get("plan_revision")
    if not isinstance(br,int) or br<1: err(f"work packet {wid}: baseline_revision must be >=1")
    if not isinstance(pr,int) or pr<1: err(f"work packet {wid}: plan_revision must be >=1")
    if isinstance(br,int) and br < d.get("baseline_revision",1) and s in {"planned","in_progress","blocked"}:
        warn(f"work packet {wid}: stale baseline revision {br} < current {d.get('baseline_revision')}")
    if isinstance(pr,int) and pr < d.get("plan_revision",1) and s in {"planned","in_progress","blocked"}:
        warn(f"work packet {wid}: stale plan revision {pr} < current {d.get('plan_revision')}")

for mid in d.get("active_milestones",[]):
    if mid not in ms: err(f"active milestone {mid}: not found")
    elif ms[mid].get("status") not in {"in_progress","blocked"}: warn(f"active milestone {mid}: status is {ms[mid].get('status')}")
for wid in d.get("active_work_packets",[]):
    if wid not in wps: err(f"active work packet {wid}: not found")
    elif wps[wid].get("status") not in {"in_progress","blocked"}: warn(f"active work packet {wid}: status is {wps[wid].get('status')}")
for target in d.get("resume_queue",[]):
    if target not in wps and target not in ms: err(f"resume_queue: unknown target {target}")

seen=set(); last_to=0
for pd in d.get("plan_deltas",[]):
    pid=pd.get("id")
    if not pid: err("plan delta missing id")
    elif pid in seen: err(f"duplicate active plan delta id {pid}")
    seen.add(pid)
    fr=pd.get("from_plan_revision"); to=pd.get("to_plan_revision")
    if not isinstance(fr,int) or not isinstance(to,int) or to != fr+1:
        err(f"plan delta {pid or '?'}: revisions must be consecutive integers")
    last_to=max(last_to, to if isinstance(to,int) else 0)
for pd in d.get("archived_plan_deltas",[]):
    pid=pd.get("id") if isinstance(pd,dict) else pd
    if pid in seen: err(f"plan delta {pid}: appears in both active and archived lists")
    if pid: seen.add(pid)
if last_to and last_to > d.get("plan_revision",0): err("plan_deltas reference a revision newer than current plan_revision")

canon=d.get("canonicalized_through_plan_revision")
if canon is not None:
    if not isinstance(canon,int) or canon<1: err("canonicalized_through_plan_revision must be >=1")
    elif canon > d.get("plan_revision",0): err("canonicalized_through_plan_revision cannot exceed plan_revision")

for name in ("plan_consistency","convergence"):
    g=d.get("gates",{}).get(name)
    if not isinstance(g,dict): err(f"gates.{name} must be an object"); continue
    if g.get("status") not in GATE: err(f"gates.{name}: invalid status {g.get('status')!r}")
    for rk in ("baseline_revision","plan_revision"):
        if not isinstance(g.get(rk),int) or g.get(rk)<1: err(f"gates.{name}.{rk} must be >=1")

pc=d.get("gates",{}).get("plan_consistency",{})
if d.get("active_work_packets"):
    if pc.get("status") not in {"passed","passed_with_explicit_gaps"}:
        warn("active work exists but current plan_consistency gate is not passed")
    if pc.get("baseline_revision") != d.get("baseline_revision") or pc.get("plan_revision") != d.get("plan_revision"):
        warn("plan_consistency gate revisions differ from current baseline/plan; targeted re-analysis may be required")

if warnings:
    for w in warnings: print("CONTROL WARNING:", w, file=sys.stderr)
if errors:
    for e in errors: print("CONTROL ERROR:", e, file=sys.stderr)
    print(f"CONTROL INVALID: {len(errors)} error(s), {len(warnings)} warning(s)", file=sys.stderr)
    sys.exit(2)
print(f"CONTROL VALID: {path} ({len(warnings)} warning(s))")
