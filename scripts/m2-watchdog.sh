#!/usr/bin/env bash
set -uo pipefail

# M1-side health watchdog for the local AI stack. Installed as a launchd StartInterval agent
# (com.localai.m2-watchdog) that fires ~every 60s and performs SAFE recovery only (best-effort
# Wake-on-LAN + restarts of LOCAL launchd services; cooldown-gated so it never thrashes). It covers:
#   1. M2 worker reachability (nc) → WoL + meter restart if M2 dropped.
#   2. The meter wedging on stale connections after a link flap (M2 up but the proxy 502s) → meter restart.
#   3. The M1 orchestrator wedging (answers /models but hangs on /chat/completions after long uptime) →
#      orchestrator restart, distinguishing a true wedge from a merely-busy server via telemetry.
# No destructive actions, ever.
#
# Env overrides: M2_HOST, M2_PORTS, METER_PORTS, METER_LABEL, M2_RECOVER_COOLDOWN, ORCH_URL, ORCH_MODEL,
# ORCH_LABEL, ORCH_BAD_LIMIT, ORCH_BUSY_WINDOW, M2_WATCHDOG_DRYRUN(=1 to log intended actions only).

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

# --- Orchestrator (M1, local) wedge detection ---
ORCH_URL="${ORCH_URL:-http://127.0.0.1:8001}"
ORCH_MODEL="${ORCH_MODEL:-/Users/kenallred/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16}"
ORCH_LABEL="${ORCH_LABEL:-com.localai.orchestrator}"
ORCH_PROBE_TIMEOUT="${ORCH_PROBE_TIMEOUT:-30}"
ORCH_BAD_LIMIT="${ORCH_BAD_LIMIT:-3}"        # consecutive wedged ticks before the (expensive) 35B reload
ORCH_BUSY_WINDOW="${ORCH_BUSY_WINDOW:-180}"  # a real orchestrator completion this recent => busy, not wedged
ORCH_STATE="${ORCH_STATE:-$HOME_DIR/ai/logs/m2-watchdog-orch.state}"
TELEMETRY_DB="${TELEMETRY_DB:-$HOME_DIR/ai/dashboard/telemetry.db}"

probe_orchestrator() {  # 0 iff the orchestrator COMPLETES a tiny request (real inference, not just /models)
  command -v curl >/dev/null 2>&1 || return 0  # no curl → can't check; don't false-trigger
  local code
  code="$(curl -s -m "$ORCH_PROBE_TIMEOUT" -o /dev/null -w '%{http_code}' "$ORCH_URL/v1/chat/completions" \
    -H 'content-type: application/json' \
    --data "{\"model\":\"$ORCH_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":1}" 2>/dev/null || echo 000)"
  [ "$code" = "200" ]
}

orchestrator_served_recently() {  # 0 iff a successful orchestrator completion is in telemetry within the window
  command -v sqlite3 >/dev/null 2>&1 || return 1  # can't tell → treat as not-recent, lean on the probe
  [ -f "$TELEMETRY_DB" ] || return 1
  local last
  last="$(sqlite3 "$TELEMETRY_DB" "SELECT COALESCE(MAX(ts),0) FROM requests WHERE upstream='orchestrator' AND error_class='ok';" 2>/dev/null || echo 0)"
  [ -n "$last" ] || last=0
  [ $(( now * 1000 - last )) -lt $(( ORCH_BUSY_WINDOW * 1000 )) ]
}

# ---- load prior state (status=up|down, last_recover=epoch) ----
status="unknown"; last_recover=0; meter_bad=0
# shellcheck disable=SC1090
[ -f "$STATE" ] && . "$STATE" 2>/dev/null || true
prev_status="$status"
now="$(date +%s)"

# status=up|down, last_recover=epoch of last recovery action, meter_bad=consecutive wedged-meter ticks
write_state() { printf 'status=%s\nlast_recover=%s\nmeter_bad=%s\n' "$1" "$2" "${3:-0}" > "$STATE"; }

# ---- Orchestrator (M1) wedge check — independent of M2; runs every tick, then falls through ----
# The mlx server can answer /models yet hang on /chat/completions after long uptime (the 12-day
# incident: process idle at 0% CPU). A real completion probe is the only true health test, but it ALSO
# times out when the orchestrator is merely BUSY (mlx serializes), so a probe failure counts as
# "wedged" only when no real orchestrator completion succeeded recently. Same pattern as the meter fix.
orch_bad=0; orch_last_recover=0
# shellcheck disable=SC1090
[ -f "$ORCH_STATE" ] && . "$ORCH_STATE" 2>/dev/null || true
write_orch() { printf 'orch_bad=%s\norch_last_recover=%s\n' "$1" "$2" > "$ORCH_STATE"; }

if probe_orchestrator; then
  [ "${orch_bad:-0}" -gt 0 ] && { logln "orchestrator RECOVERED — serving completions"; notify "Orchestrator recovered ✅"; }
  write_orch 0 "$orch_last_recover"
elif orchestrator_served_recently; then
  logln "  orchestrator completion probe timed out but it served recently — busy, not wedged"
  write_orch 0 "$orch_last_recover"
else
  orch_bad=$(( orch_bad + 1 ))
  if [ "$orch_bad" -ge "$ORCH_BAD_LIMIT" ] && [ $(( now - orch_last_recover )) -ge "$COOLDOWN" ]; then
    if [ "$DRYRUN" = "1" ]; then
      logln "  [dry-run] orchestrator WEDGED (completion probe failed x$orch_bad, no recent traffic) — would restart $ORCH_LABEL"
    else
      logln "  orchestrator WEDGED — hangs on completions while idle (probe x$orch_bad); restarting $ORCH_LABEL"
      launchctl kickstart -k "gui/$UID_NUM/$ORCH_LABEL" >> "$LOG" 2>&1 || logln "  orchestrator kickstart failed"
      notify "Orchestrator unwedged 🔧 — it was hung on completions; restarting (reloads the 35B)"
    fi
    write_orch 0 "$now"
  else
    logln "  orchestrator completion probe failing (x$orch_bad) — watching before the (expensive) reload"
    write_orch "$orch_bad" "$orch_last_recover"
  fi
fi

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
