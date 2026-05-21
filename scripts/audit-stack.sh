#!/usr/bin/env bash
set -euo pipefail

# Launch Claude Code with the right directory scope and an initial audit
# prompt. Anything passed to this script is forwarded as the focus area
# argument to the /audit-stack slash command (or appended to the
# free-form prompt if you don't have slash-command support).
#
# Usage:
#   scripts/audit-stack.sh                    # full audit
#   scripts/audit-stack.sh "launchd only"     # focused audit

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Build --add-dir flags only for directories that actually exist on this
# Mac. Claude Code refuses to start if you point --add-dir at a missing
# path, so the audit launcher must skip-if-missing rather than hardcode.
DIRS=(
  "$HOME/ai"
  "$HOME/Library/LaunchAgents"
  "$HOME/.claude/skills"
  "$HOME/.codex"
)
ADDS=()
for d in "${DIRS[@]}"; do
  if [ -d "$d" ]; then
    ADDS+=(--add-dir "$d")
  else
    echo "[skip] $d (not present yet)" >&2
  fi
done

# Initial prompt. If you have project slash commands enabled, prefer
# `/audit-stack`; otherwise we inline the equivalent instructions.
FOCUS="${*:-}"
PROMPT=$(cat <<EOF
/audit-stack $FOCUS
EOF
)

echo "+ cd $REPO_DIR"
echo "+ claude ${ADDS[*]:-} (initial prompt: /audit-stack $FOCUS)"
echo

exec claude "${ADDS[@]:-}" "$PROMPT"
