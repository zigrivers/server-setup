#!/usr/bin/env bash
set -uo pipefail

# M1 watchdog for Machine 2 (the inference worker). Installed as a launchd StartInterval agent
# (com.localai.m2-watchdog) that fires ~every 60s. Each tick it probes M2's worker ports; if M2 has
# dropped it performs SAFE recovery only — a best-effort Wake-on-LAN packet, a restart of the LOCAL
# meter to clear stale connection state (the exact fix from the live incident), and a desktop notify.
# It acts on state transitions / a cooldown, so it never thrashes. No destructive actions, ever.
#
# Env overrides: M2_HOST, M2_PORTS, METER_LABEL, M2_RECOVER_COOLDOWN, M2_WATCHDOG_DRYRUN(=1 to log
# intended actions without performing them — used by the test harness).

HOME_DIR="${HOME:-/Users/$(id -un)}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
M2_HOST="${M2_HOST:-10.10.10.2}"
read -r -a PORTS <<< "${M2_PORTS:-8002 8003}"
read -r -a METER_PORTS <<< "${METER_PORTS:-9002 9003}"  # local meter ports that proxy to the M2 workers
METER_LABEL="${METER_LABEL:-com.localai.dashboard.meter}"
UID_NUM="$(id -u)"
LOG="${M2_WATCHDOG_LOG:-$HOME_DIR/ai/logs/m2-watchdog.log}"
STATE="${M2_WATCHDOG_STATE:-$HOME_DIR/ai/logs/m2-watchdog.state}"
COOLDOWN="${M2_RECOVER_COOLDOWN:-300}"   # min seconds between recovery attempts (anti-thrash)
DRYRUN="${M2_WATCHDOG_DRYRUN:-0}"
mkdir -p "$(dirname "$LOG")"

ts()   { date "+%Y-%m-%dT%H:%M:%S%z"; }
logln() { printf "%s  %s\n" "$(ts)" "$1" >> "$LOG"; }
notify() { command -v launchpad >/dev/null 2>&1 && launchpad notify "$1" >/dev/null 2>&1 || true; }

probe() {  # 0 iff every worker port is reachable
  local p
  for p in "${PORTS[@]}"; do
    nc -z -G 3 "$M2_HOST" "$p" >/dev/null 2>&1 || return 1
  done
  return 0
}

probe_meter() {  # 0 iff the local meter can actually PROXY to each M2 worker (HTTP 200), not just M2 being reachable
  command -v curl >/dev/null 2>&1 || return 0   # no curl → can't check; don't false-trigger a restart
  local mp code
  for mp in "${METER_PORTS[@]}"; do
    code="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$mp/v1/models" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] || return 1
  done
  return 0
}

# ---- load prior state (status=up|down, last_recover=epoch) ----
status="unknown"; last_recover=0; meter_bad=0
# shellcheck disable=SC1090
[ -f "$STATE" ] && . "$STATE" 2>/dev/null || true
prev_status="$status"
now="$(date +%s)"

# status=up|down, last_recover=epoch of last recovery action, meter_bad=consecutive wedged-meter ticks
write_state() { printf 'status=%s\nlast_recover=%s\nmeter_bad=%s\n' "$1" "$2" "${3:-0}" > "$STATE"; }

# ---- M2 reachable directly ----
if probe; then
  [ "$prev_status" = "down" ] && { logln "M2 RECOVERED — ports ${PORTS[*]} reachable"; notify "M2 worker recovered ✅"; }
  # M2's ports answer, but the meter can still be wedged on stale connections after a Thunderbolt link
  # flap (M2 up, yet every proxied request 502s — the exact 2026-06-29 incident). Detect by probing M2
  # THROUGH the meter; require 2 consecutive bad ticks so a transient blip doesn't trigger a restart.
  if probe_meter; then
    write_state up "$last_recover" 0
    exit 0
  fi
  meter_bad=$((meter_bad + 1))
  if [ "$meter_bad" -lt 2 ]; then
    logln "  meter path failing while M2 reachable (x$meter_bad) — watching before acting"
    write_state up "$last_recover" "$meter_bad"; exit 0
  fi
  if [ $((now - last_recover)) -lt "$COOLDOWN" ]; then
    logln "  meter wedged (x$meter_bad) but within ${COOLDOWN}s cooldown — no action this tick"
    write_state up "$last_recover" "$meter_bad"; exit 0
  fi
  if [ "$DRYRUN" = "1" ]; then
    logln "  [dry-run] meter wedged (M2 reachable, meter path failing x$meter_bad) — would restart $METER_LABEL"
    write_state up "$now" 0; exit 0
  fi
  logln "  meter WEDGED — M2 reachable but meter path failing (x$meter_bad); restarting $METER_LABEL"
  launchctl kickstart -k "gui/$UID_NUM/$METER_LABEL" >> "$LOG" 2>&1 || logln "  meter kickstart failed"
  notify "Meter unwedged 🔧 — M2 was reachable but the proxy had stalled"
  write_state up "$now" 0
  exit 0
fi

# ---- down ----
logln "M2 DOWN — port(s) ${PORTS[*]} unreachable on $M2_HOST"

if [ $((now - last_recover)) -lt "$COOLDOWN" ]; then
  logln "  within ${COOLDOWN}s recovery cooldown — no action this tick"
  write_state down "$last_recover"
  exit 0
fi

[ "$prev_status" != "down" ] && notify "M2 worker dropped ⚠️ — attempting auto-recovery"

# 1) best-effort wake
if [ "$DRYRUN" = "1" ]; then
  logln "  [dry-run] would send Wake-on-LAN to M2"
else
  logln "  sending Wake-on-LAN magic packet to M2"
  "$SCRIPTS_DIR/wol-m2.sh" >> "$LOG" 2>&1 || logln "  WoL send failed (continuing)"
  sleep 5
fi

# 2) clear a wedged meter (stale connection state after M2 sleep/wake)
if [ "$DRYRUN" = "1" ]; then
  logln "  [dry-run] would kickstart meter ($METER_LABEL)"
else
  logln "  restarting meter ($METER_LABEL) to clear stale connections"
  launchctl kickstart -k "gui/$UID_NUM/$METER_LABEL" >> "$LOG" 2>&1 || logln "  meter kickstart failed"
  sleep 3
fi

# 3) re-probe + report
if [ "$DRYRUN" = "1" ]; then
  logln "  [dry-run] would re-probe and notify"; write_state down "$now"; exit 0
fi
if probe; then
  logln "  RECOVERED after action"; notify "M2 worker recovered ✅"; write_state up "$now"
else
  logln "  STILL DOWN after WoL + meter restart — likely asleep/off; manual wake may be needed"
  notify "M2 still down ❌ — may need a manual wake"; write_state down "$now"
fi
exit 0
