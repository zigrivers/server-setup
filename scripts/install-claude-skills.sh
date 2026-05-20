#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$HOME/.claude/skills"

for skill in delegate-local local-review local-ai-status; do
  rm -rf "$HOME/.claude/skills/$skill"
  cp -R "$REPO_DIR/skills/claude/$skill" "$HOME/.claude/skills/$skill"
done

echo "Installed Claude skills:"
ls "$HOME/.claude/skills"

echo "Restart Claude Code, then run /skills."
