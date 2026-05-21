#!/usr/bin/env bash
set -euo pipefail

# Install the Machine 2 workers as two LaunchDaemons in /Library/LaunchDaemons/.
# Daemons load at boot (no console login required), which matters for the
# headless, FileVault-encrypted Machine 2. Each daemon runs as the current
# user via UserName=<whoami> so it can read $HOME/ai/models and the venv.
#
# Boots out and removes the obsolete com.localai.workers LaunchAgent if
# present. Requires sudo (prompts once interactively).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DAEMON_DIR="/Library/LaunchDaemons"
UID_NUM="$(id -u)"
WORKER_USER="${WORKER_USER:-$(id -un)}"   # default to current user (admin on M2)
WORKER_HOME="${WORKER_HOME:-$HOME}"

mkdir -p "$HOME/ai/logs"

# --- Phase 1: bootout/remove the obsolete com.localai.workers LaunchAgent ---
OLD_LABEL="com.localai.workers"
OLD_AGENT_DEST="$HOME/Library/LaunchAgents/${OLD_LABEL}.plist"
for DOMAIN in "gui/$UID_NUM" "user/$UID_NUM"; do
  if launchctl print "$DOMAIN/$OLD_LABEL" >/dev/null 2>&1; then
    echo "Unloading obsolete $DOMAIN/$OLD_LABEL"
    launchctl bootout "$DOMAIN/$OLD_LABEL" || true
  fi
done
if [ -f "$OLD_AGENT_DEST" ]; then
  echo "Removing obsolete $OLD_AGENT_DEST"
  rm -f "$OLD_AGENT_DEST"
fi

# --- Phase 2: install LaunchDaemons under sudo ---
echo "Installing LaunchDaemons (sudo required)..."
sudo -v

install_daemon() {
  local LABEL="$1"
  local SRC="$REPO_DIR/configs/launchd/${LABEL}.plist.template"
  local DEST="$DAEMON_DIR/${LABEL}.plist"
  local TMP
  TMP="$(mktemp)"

  if [ ! -f "$SRC" ]; then
    echo "Template not found: $SRC" >&2
    exit 1
  fi

  sed -e "s|__USER__|$WORKER_USER|g" -e "s|__HOME__|$WORKER_HOME|g" "$SRC" > "$TMP"

  if ! plutil -lint "$TMP" >/dev/null; then
    echo "Rendered plist failed plutil -lint: $TMP" >&2
    cat "$TMP" >&2
    rm -f "$TMP"
    exit 1
  fi

  if sudo launchctl print "system/$LABEL" >/dev/null 2>&1; then
    echo "Unloading existing system/$LABEL"
    sudo launchctl bootout "system/$LABEL" || true
  fi

  sudo install -o root -g wheel -m 644 "$TMP" "$DEST"
  rm -f "$TMP"
  echo "Wrote $DEST (root:wheel 644)"

  echo "Loading system/$LABEL"
  sudo launchctl bootstrap system "$DEST"
  sudo launchctl enable "system/$LABEL"
}

install_daemon com.localai.developer
install_daemon com.localai.reviewer

echo
echo "Installed. Status:"
sudo launchctl print "system/com.localai.developer" | head -10 || true
echo "---"
sudo launchctl print "system/com.localai.reviewer"  | head -10 || true
echo
echo "Logs:"
echo "  $HOME/ai/logs/{developer,reviewer}-launchd.{out,err}"
echo "  $HOME/ai/logs/{developer,reviewer}.log  (from the launcher scripts)"
echo
echo "To uninstall both:"
echo "  sudo launchctl bootout system/com.localai.developer && sudo rm '$DAEMON_DIR/com.localai.developer.plist'"
echo "  sudo launchctl bootout system/com.localai.reviewer  && sudo rm '$DAEMON_DIR/com.localai.reviewer.plist'"
