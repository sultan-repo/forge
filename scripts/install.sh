#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/forge"

mkdir -p "$(dirname "$DEST_DIR")"

SOURCE_REAL="$(cd "$SOURCE_DIR" && pwd -P)"
DEST_REAL="$(cd "$(dirname "$DEST_DIR")" && pwd -P)/$(basename "$DEST_DIR")"

if [ "$SOURCE_REAL" = "$DEST_REAL" ]; then
  if command -v python3 >/dev/null 2>&1; then
    python3 "$SOURCE_DIR/scripts/validate-skill-package.py"
  fi
  echo "Forge is already installed at $DEST_DIR"
  exit 0
fi

STAGING_DIR="$(mktemp -d "$(dirname "$DEST_DIR")/.forge-install.XXXXXX")"
BACKUP=""
LOCK_DIR="$(dirname "$DEST_DIR")/.forge-install.lock"
LOCK_HELD=false
cleanup() {
  result=$?
  trap - EXIT
  rm -rf "$STAGING_DIR"
  if [[ $result -ne 0 && -n "$BACKUP" && ! -e "$DEST_DIR" && ! -L "$DEST_DIR" ]]; then
    mv "$BACKUP" "$DEST_DIR"
    echo "Forge installation failed; restored the previous installation." >&2
  fi
  if [[ "$LOCK_HELD" == true ]]; then
    rmdir "$LOCK_DIR"
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another Forge install is active ($LOCK_DIR). If it was interrupted, remove that empty lock directory and retry." >&2
  exit 2
fi
LOCK_HELD=true

for item in SKILL.md README.md BOOTSTRAP.md CONTRIBUTING.md CHANGELOG.md VERSION LICENSE .github references templates evals scripts docs tests requirements-dev.txt; do
  if [ -e "$SOURCE_DIR/$item" ]; then
    cp -R "$SOURCE_DIR/$item" "$STAGING_DIR/"
  fi
done

find "$STAGING_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGING_DIR" -type f -name '*.pyc' -delete
# Generated benchmark work and results are local evidence, not distributable assets.
rm -rf "$STAGING_DIR/evals/core/build" "$STAGING_DIR/evals/core/results"
rm -f "$STAGING_DIR/evals/core/fixture_bundle.json"

if command -v python3 >/dev/null 2>&1; then
  python3 "$STAGING_DIR/scripts/validate-skill-package.py"
else
  echo "Forge package validation skipped: Python is unavailable." >&2
fi

if [[ -e "$DEST_DIR" || -L "$DEST_DIR" ]]; then
  BACKUP="$(mktemp -d "${DEST_DIR}.backup.XXXXXX")"
  rmdir "$BACKUP"
  mv "$DEST_DIR" "$BACKUP"
  echo "Previous Forge installation preserved at $BACKUP"
fi
mv "$STAGING_DIR" "$DEST_DIR"

echo "Forge installed at $DEST_DIR"
echo "If command discovery is not live in this environment, load SKILL.md directly for the current session and reload later for /forge registration."
