#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
Forge bootstrap helper

This helper executes code from the Forge package. Do not run it directly from
a newly downloaded/unverified remote source.

First establish source provenance using the strongest mechanism available in
your environment. Prefer a verified immutable/versioned release when supported.
If only a commit-pinned source is available, use agent-controlled file copying
instead of executing this script.

After provenance is established, run:
  FORGE_SOURCE_VERIFIED=1 ./scripts/bootstrap.sh
EOF

if [[ "${FORGE_SOURCE_VERIFIED:-}" != "1" ]]; then
  exit 2
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$SOURCE_DIR/scripts/install.sh"

cat <<EOF
FORGE_BOOTSTRAP_READY

Load ${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/forge/SKILL.md directly for the current session.
Treat the user's explicit Forge request as invocation.
Infer new for greenfield or adopt for existing work unless a mode was supplied.
Do not require a restart merely to continue the current task.
EOF
