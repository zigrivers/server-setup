#!/usr/bin/env bash
set -euo pipefail

# Install the Machine 2 workers launchd agent.
# Reads configs/launchd/com.localai.workers.plist.template, substitutes
# __HOME__, and bootstraps it into the per-user GUI domain. The agent
# runs scripts/start-worker-models.sh which starts both Developer (8002)
# and Reviewer (8003).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/configs/launchd/com.localai.workers.plist.template"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST="$DEST_DIR/com.localai.workers.plist"
LABEL="com.localai.workers"

if [ ! -f "$SRC" ]; then
  echo "Template not found: $SRC" >&2
  exit 1
fi

mkdir -p "$DEST_DIR" "$HOME/ai/logs"

sed "s|__HOME__|$HOME|g" "$SRC" > "$DEST"
echo "Wrote $DEST"

UID_NUM="$(id -u)"
if launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
  echo "Unloading existing $LABEL"
  launchctl bootout "gui/$UID_NUM/$LABEL" || true
fi

echo "Loading $LABEL"
launchctl bootstrap "gui/$UID_NUM" "$DEST"
launchctl enable "gui/$UID_NUM/$LABEL"

echo
echo "Installed. Status:"
launchctl print "gui/$UID_NUM/$LABEL" | head -20 || true
echo
echo "Logs:"
echo "  $HOME/ai/logs/workers-launchd.{out,err}"
echo "  $HOME/ai/logs/{developer,reviewer}.log  (from the launcher script)"
echo "To uninstall: launchctl bootout gui/$UID_NUM/$LABEL && rm '$DEST'"
