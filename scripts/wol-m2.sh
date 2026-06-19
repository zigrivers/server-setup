#!/usr/bin/env bash
set -euo pipefail

# Send a Wake-on-LAN "magic packet" to Machine 2 over the Thunderbolt bridge.
#
# Best-effort only: WoL can wake a *sleeping* Mac whose NIC honors it (requires `sudo pmset -a womp 1`
# on M2), but cannot wake a powered-off machine, and Thunderbolt-bridge NICs don't always support it.
# The primary defense against M2 dropping is preventing sleep (pmset + caffeinate); this is a bonus.
#
# Usage: wol-m2.sh [MAC] [BROADCAST]
#   env overrides: M2_MAC, M2_BROADCAST, M2_WOL_PORT

MAC="${1:-${M2_MAC:-36:30:71:34:62:c0}}"
BCAST="${2:-${M2_BROADCAST:-10.10.10.255}}"
PORT="${M2_WOL_PORT:-9}"

/usr/bin/env python3 - "$MAC" "$BCAST" "$PORT" <<'PY'
import socket, sys
mac, bcast, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
hw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
if len(hw) != 6:
    raise SystemExit("bad MAC address: %r" % mac)
packet = b"\xff" * 6 + hw * 16          # 6 bytes of 0xFF + the target MAC repeated 16 times
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
s.sendto(packet, (bcast, port))
s.close()
print("WoL magic packet sent to %s via %s:%d" % (mac, bcast, port))
PY
