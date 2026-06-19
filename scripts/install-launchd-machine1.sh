#!/usr/bin/env bash
set -euo pipefail

# Install the Machine 1 launchd LaunchAgents (orchestrator + RAG proxy).
# For each: read configs/launchd/<label>.plist.template, substitute __HOME__ with the current user's
# home, write the rendered plist into ~/Library/LaunchAgents, and bootstrap it into the per-user GUI
# domain. Idempotent (boots out an existing agent first).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"
mkdir -p "$DEST_DIR" "$HOME/ai/logs"

install_agent() {
  local LABEL="$1"
  local SRC="$REPO_DIR/configs/launchd/${LABEL}.plist.template"
  local DEST="$DEST_DIR/${LABEL}.plist"

  if [ ! -f "$SRC" ]; then
    echo "Template not found: $SRC" >&2
    exit 1
  fi

  sed "s|__HOME__|$HOME|g" "$SRC" > "$DEST"
  chmod 644 "$DEST"
  echo "Wrote $DEST"

  if launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; then
    echo "Unloading existing $LABEL"
    launchctl bootout "gui/$UID_NUM/$LABEL" || true
  fi
  echo "Loading $LABEL"
  launchctl bootstrap "gui/$UID_NUM" "$DEST"
  launchctl enable "gui/$UID_NUM/$LABEL"
  echo
}

# Allow installing a subset: `install-launchd-machine1.sh rag-proxy` installs only that one.
AGENTS=("com.localai.orchestrator" "com.localai.rag-proxy" "com.localai.m2-watchdog")
if [ $# -gt 0 ]; then
  AGENTS=()
  for a in "$@"; do AGENTS+=("com.localai.$a"); done
fi

for LABEL in "${AGENTS[@]}"; do
  install_agent "$LABEL"
done

echo "Installed: ${AGENTS[*]}"
echo "Status:  launchctl print gui/$UID_NUM/<label> | head -20"
echo "Logs:    $HOME/ai/logs/{orchestrator,rag-proxy,m2-watchdog}-launchd.{out,err}  + ~/ai/logs/{rag-proxy,m2-watchdog}.log"
echo "Uninstall: launchctl bootout gui/$UID_NUM/<label> && rm $DEST_DIR/<label>.plist"
