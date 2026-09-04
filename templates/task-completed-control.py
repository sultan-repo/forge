#!/usr/bin/env python3
"""Optional Forge TaskCompleted guard.

Only applies when the completed task explicitly references a Forge Work Packet
ID (for example "[WP-3.4] ..."). If no Work Packet is referenced, the hook
stays out of the way. This keeps Forge adaptive to environments/projects that
do not use a native task lifecycle.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    event = json.load(sys.stdin)
except Exception:
    sys.exit(0)

text = " ".join(str(event.get(k) or "") for k in ("task_subject", "task_description"))
m = re.search(r"\b(WP-[A-Za-z0-9._-]+)\b", text)
if not m:
    sys.exit(0)

wp_id = m.group(1)
cwd = Path(event.get("cwd") or ".")
state_path = cwd / ".claude" / "project-control.json"
validator = cwd / ".claude" / "hooks" / "validate-project-control.py"

if not state_path.exists():
    print(f"Forge: task references {wp_id}, but {state_path} is missing.", file=sys.stderr)
    sys.exit(2)

try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"Forge: cannot parse project control state: {exc}", file=sys.stderr)
    sys.exit(2)

wp = state.get("work_packets", {}).get(wp_id)
if not isinstance(wp, dict):
    print(f"Forge: task references unknown Work Packet {wp_id}.", file=sys.stderr)
    sys.exit(2)

if validator.exists():
    p = subprocess.run([sys.executable, str(validator), str(state_path)], capture_output=True, text=True)
    if p.returncode != 0:
        detail = (p.stderr or p.stdout).strip()
        print(f"Forge: control state invalid before completing {wp_id}: {detail}", file=sys.stderr)
        sys.exit(2)

accepted = {"passed", "satisfied", "accepted", "complete", "completed"}
if str(wp.get("acceptance_status", "")).lower() not in accepted:
    print(f"Forge: {wp_id} acceptance_status is not complete.", file=sys.stderr)
    sys.exit(2)
if str(wp.get("validation_status", "")).lower() not in accepted:
    print(f"Forge: {wp_id} validation_status is not complete.", file=sys.stderr)
    sys.exit(2)
if wp.get("reconciled") is not True:
    print(f"Forge: {wp_id} is not reconciled back to the project plan.", file=sys.stderr)
    sys.exit(2)

sys.exit(0)
