#!/usr/bin/env bash
set -euo pipefail

# Install the Machine 1 Orchestrator launchd agent.
# Reads configs/launchd/com.localai.orchestrator.plist.template, substitutes
# __HOME__ with the current user's home, writes the rendered plist into
# ~/Library/LaunchAgents, and bootstraps it into the per-user GUI domain.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/configs/launchd/com.localai.orchestrator.plist.template"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST="$DEST_DIR/com.localai.orchestrator.plist"
LABEL="com.localai.orchestrator"

if [ ! -f "$SRC" ]; then
  echo "Template not found: $SRC" >&2
  exit 1
fi

mkdir -p "$DEST_DIR" "$HOME/ai/logs"

# Render template
sed "s|__HOME__|$HOME|g" "$SRC" > "$DEST"
echo "Wrote $DEST"

# Bootstrap (idempotent: bootout first if already loaded)
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
echo "Logs: $HOME/ai/logs/orchestrator-launchd.{out,err}"
echo "To uninstall: launchctl bootout gui/$UID_NUM/$LABEL && rm '$DEST'"
