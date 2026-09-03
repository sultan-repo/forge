#!/usr/bin/env python3
"""Structural validation for the forge skill package."""
from pathlib import Path
import json, re, subprocess, sys

root = Path(__file__).resolve().parents[1]
errors=[]; warnings=[]

def err(x): errors.append(x)
def warn(x): warnings.append(x)

skill = root / "SKILL.md"
if not skill.exists(): err("SKILL.md missing")
else:
    text=skill.read_text(encoding="utf-8")
    lines=text.count("\n")+1
    if lines >= 500: err(f"SKILL.md is {lines} lines; must stay under 500")
    if not text.startswith("---\n"): err("SKILL.md missing YAML frontmatter")
    if "disable-model-invocation: true" not in text: warn("skill is no longer manual-only")
    # Check relative links in the skill body.
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if "://" in target or target.startswith("#"): continue
        p=(root/target).resolve()
        try: p.relative_to(root.resolve())
        except ValueError: err(f"skill link escapes package: {target}"); continue
        if not p.exists(): err(f"SKILL.md references missing file: {target}")

version=(root/"VERSION").read_text(encoding="utf-8").strip() if (root/"VERSION").exists() else None
if version != "1.4.0": err(f"VERSION expected 1.4.0, got {version!r}")

# Parse all packaged JSON.
for p in root.rglob("*.json"):
    try: json.loads(p.read_text(encoding="utf-8"))
    except Exception as e: err(f"invalid JSON {p.relative_to(root)}: {e}")

# Basic eval schema.
evals_path=root/"evals"/"evals.json"
if not evals_path.exists(): err("evals/evals.json missing")
else:
    try: e=json.loads(evals_path.read_text(encoding="utf-8"))
    except Exception: e={}
    if e.get("skill_name") != "forge": err("evals skill_name mismatch")
    ids=set()
    for item in e.get("evals",[]):
        for k in ("id","prompt","expected_output","expectations"):
            if k not in item: err(f"eval missing {k}: {item.get('id')}")
        if item.get("id") in ids: err(f"duplicate eval id {item.get('id')}")
        ids.add(item.get("id"))
        if not item.get("expectations"): err(f"eval {item.get('id')} has no expectations")

# Validate control example with packaged validator.
validator=root/"templates"/"validate-project-control.py"
example=root/"templates"/"project-control.example.json"
if validator.exists() and example.exists():
    p=subprocess.run([sys.executable,str(validator),str(example)],capture_output=True,text=True)
    if p.returncode != 0: err("control example failed validator: "+(p.stderr.strip() or p.stdout.strip()))
else: err("control validator/example missing")

# Expected package files.
for rel in [
    "references/requirements.md",
    "references/architecture-and-structure.md",
    "references/scope-and-plan-control.md",
    "references/consistency-and-convergence.md",
    "references/orchestration.md",
    "references/execution-and-quality.md",
    "references/trust-and-security.md",
    "references/context-and-governance.md",
    "references/full-spectrum-validation.md",
    "templates/execution-control-kernel.md",
    "templates/project-control.schema.json",
    "templates/session-start-control.py",
]:
    if not (root/rel).exists(): err(f"required package file missing: {rel}")

for w in warnings: print("SKILL WARNING:", w, file=sys.stderr)
if errors:
    for e in errors: print("SKILL ERROR:", e, file=sys.stderr)
    print(f"SKILL INVALID: {len(errors)} error(s), {len(warnings)} warning(s)", file=sys.stderr)
    sys.exit(2)
print(f"SKILL VALID: forge {version} ({len(warnings)} warning(s))")
