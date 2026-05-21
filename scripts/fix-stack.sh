#!/usr/bin/env bash
set -euo pipefail

# Launch Claude Code with the right directory scope and an initial
# remediation prompt. Mirrors scripts/audit-stack.sh but invokes the
# /fix-stack slash command, which is permitted to *change* deployment
# state (within the safety bucket rules documented in
# .claude/commands/fix-stack.md).
#
# Usage:
#   scripts/fix-stack.sh                    # full remediation
#   scripts/fix-stack.sh "launchd only"     # focused

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

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

FOCUS="${*:-}"
PROMPT=$(cat <<EOF
/fix-stack $FOCUS
EOF
)

cat <<MSG
+ cd $REPO_DIR
+ claude ${ADDS[*]:-} (initial prompt: /fix-stack $FOCUS)

The /fix-stack command will auto-run idempotent install scripts but
will ASK before doing anything that could overwrite your edits, touch
Machine 2 over SSH, or trigger model downloads.

MSG

exec claude "${ADDS[@]:-}" "$PROMPT"
