#!/usr/bin/env bash
set -euo pipefail

# Apply Machine 2 keep-alive from Machine 1 over SSH. M2's account is `admin` (the Mac Studio).
# Requires passwordless SSH to M2 first. NOTE M2's SSH closes the connection on keyboard-interactive
# auth, so force password auth when installing the key:
#   cat ~/.ssh/id_ed25519.pub | ssh -o PreferredAuthentications=password admin@10.10.10.2 \
#       'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys; echo KEY_ADDED'
#
# Does two things on M2, idempotently, then verifies:
#   1) pmset anti-sleep   (needs sudo on M2 — you'll be prompted once; run this in a real terminal)
#   2) installs + loads the com.localai.caffeinate LaunchAgent (no sudo)
#
# Env overrides: M2_SSH (default admin@10.10.10.2)

M2="${M2_SSH:-admin@10.10.10.2}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO_DIR/configs/launchd/com.localai.caffeinate.plist.template"

echo "==> Verifying passwordless SSH to $M2"
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$M2" true 2>/dev/null; then
  echo "ERROR: no passwordless SSH to $M2 yet. Install the key first:" >&2
  echo "  ssh-copy-id -o PreferredAuthentications=password -o PubkeyAuthentication=no -i ~/.ssh/id_ed25519.pub $M2" >&2
  exit 1
fi
echo "    ok"

echo "==> (1/2) pmset anti-sleep on M2 (sudo — enter M2's password if prompted)"
ssh -t "$M2" 'sudo pmset -a sleep 0 disksleep 0 powernap 0 lidwake 0 womp 1 && echo "  pmset applied:" && pmset -g | grep " sleep"'

echo "==> (2/2) caffeinate LaunchAgent on M2"
M2_HOME="$(ssh "$M2" 'printf %s "$HOME"')"
M2_UID="$(ssh "$M2" 'id -u')"
sed "s|__HOME__|$M2_HOME|g" "$TEMPLATE" \
  | ssh "$M2" 'mkdir -p ~/Library/LaunchAgents ~/ai/logs && cat > ~/Library/LaunchAgents/com.localai.caffeinate.plist'
ssh "$M2" "launchctl bootout gui/$M2_UID/com.localai.caffeinate 2>/dev/null; \
           launchctl bootstrap gui/$M2_UID ~/Library/LaunchAgents/com.localai.caffeinate.plist && \
           launchctl enable gui/$M2_UID/com.localai.caffeinate"

echo "==> Verifying M2"
ssh "$M2" "echo -n '  sleep setting: '; pmset -g | awk '/ sleep/{print \$2}'; \
           echo -n '  caffeinate agent: '; launchctl print gui/$M2_UID/com.localai.caffeinate 2>/dev/null | awk '/state =/{print \$3; found=1} END{if(!found)print \"NOT LOADED\"}'; \
           echo -n '  caffeinate running: '; pgrep -fl 'caffeinate -dimsu' >/dev/null && echo yes || echo no"
echo "Done. M2 will stay awake (pmset) and is held awake at runtime (caffeinate)."
