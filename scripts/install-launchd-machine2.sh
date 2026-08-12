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
    # bootout is asynchronous — bootstrapping immediately after it races the
    # teardown and fails with "Bootstrap failed: 5: Input/output error"
    # (observed live 2026-08-12, twice in a row). Wait for the label to
    # actually disappear before proceeding.
    for _ in $(seq 1 10); do
      sudo launchctl print "system/$LABEL" >/dev/null 2>&1 || break
      sleep 1
    done
  fi

  sudo install -o root -g wheel -m 644 "$TMP" "$DEST"
  rm -f "$TMP"
  echo "Wrote $DEST (root:wheel 644)"

  echo "Loading system/$LABEL"
  # Belt and braces: bootstrap can still hit the same transient EIO.
  BOOTSTRAPPED=0
  for ATTEMPT in 1 2 3; do
    if sudo launchctl bootstrap system "$DEST"; then
      BOOTSTRAPPED=1
      break
    fi
    [ "$ATTEMPT" -lt 3 ] && { echo "  bootstrap busy (attempt $ATTEMPT/3) — retrying in 2s"; sleep 2; }
  done
  if [ "$BOOTSTRAPPED" != "1" ]; then
    echo "bootstrap failed for system/$LABEL after 3 attempts" >&2
    exit 1
  fi
  sudo launchctl enable "system/$LABEL"
}

install_daemon com.localai.developer
install_daemon com.localai.reviewer
install_daemon com.localai.vlm-judge

echo
echo "Installed. Status:"
sudo launchctl print "system/com.localai.developer" | head -10 || true
echo "---"
sudo launchctl print "system/com.localai.reviewer"  | head -10 || true
echo "---"
sudo launchctl print "system/com.localai.vlm-judge" | head -10 || true
echo
echo "Logs:"
echo "  $HOME/ai/logs/{developer,reviewer,vlm-judge}-launchd.{out,err}"
echo "  $HOME/ai/logs/{developer,reviewer,vlm-judge}.log  (from the launcher scripts)"
echo
echo "To uninstall:"
echo "  sudo launchctl bootout system/com.localai.developer && sudo rm '$DAEMON_DIR/com.localai.developer.plist'"
echo "  sudo launchctl bootout system/com.localai.reviewer  && sudo rm '$DAEMON_DIR/com.localai.reviewer.plist'"
echo "  sudo launchctl bootout system/com.localai.vlm-judge && sudo rm '$DAEMON_DIR/com.localai.vlm-judge.plist'"
