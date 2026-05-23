#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$HOME/.gemini/antigravity-cli/skills"

for skill in delegate-local local-review local-ai-status; do
  rm -rf "$HOME/.gemini/antigravity-cli/skills/$skill"
  cp -R "$REPO_DIR/.agents/skills/$skill" "$HOME/.gemini/antigravity-cli/skills/$skill"
done

echo "Installed Antigravity skills:"
ls "$HOME/.gemini/antigravity-cli/skills"

echo "Restart Antigravity CLI, then run /skills."
