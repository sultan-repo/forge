#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v python3 >/dev/null 2>&1; then
  python3 "$SOURCE_DIR/scripts/validate-skill-package.py"
else
  echo "Forge bootstrap: python3 not available; skipping packaged validator." >&2
fi

"$SOURCE_DIR/scripts/install.sh"

cat <<'EOF'
FORGE_BOOTSTRAP_READY

Current-session instructions for the invoking coding agent:
1. Read ~/.claude/skills/forge/SKILL.md now.
2. Treat the user's explicit request to import/use Forge as an explicit Forge invocation.
3. Do not require a restart before continuing this task.
4. Infer Forge mode from project evidence: empty/greenfield -> new; existing implementation -> adopt, unless the user specified a mode.
5. Continue with the user's original project scope under Forge.

If /forge is not registered yet because ~/.claude/skills did not exist when this Claude Code session started, it may appear after a later restart. That does not block current-session Forge execution.
EOF
