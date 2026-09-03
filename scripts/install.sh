#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/forge"

mkdir -p "$(dirname "$DEST_DIR")"

if [ -e "$DEST_DIR" ]; then
  BACKUP="${DEST_DIR}.backup.$(date +%Y%m%d%H%M%S)"
  echo "Existing Forge installation found. Moving it to: $BACKUP"
  mv "$DEST_DIR" "$BACKUP"
fi

mkdir -p "$DEST_DIR"

for item in SKILL.md README.md CHANGELOG.md VERSION references templates evals scripts; do
  if [ -e "$SOURCE_DIR/$item" ]; then
    cp -R "$SOURCE_DIR/$item" "$DEST_DIR/"
  fi
done

find "$DEST_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$DEST_DIR" -type f -name '*.pyc' -delete 2>/dev/null || true

python3 "$DEST_DIR/scripts/validate-skill-package.py"
echo "Forge installed at $DEST_DIR"
echo "Restart/reload Claude Code if /forge does not appear immediately."
