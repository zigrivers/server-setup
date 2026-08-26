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
# Env overrides: M2_HOST, M2_ALT_HOST, M2_ALT_PORT, M2_PORTS, METER_PORTS, METER_LABEL, WATCHDOG_KEY,
# M2_RECOVER_COOLDOWN, ORCH_URL, ORCH_MODEL, ORCH_LABEL, ORCH_BAD_LIMIT, ORCH_PROBE_INTERVAL,
# ORCH_BUSY_WINDOW, M2_WATCHDOG_DRYRUN(=1 to log intended actions only).

HOME_DIR="${HOME:-/Users/$(id -un)}"
# launchd hands an agent only /usr/bin:/bin:/usr/sbin:/sbin, so user-installed
# tools (launchpad in ~/.local/bin, homebrew binaries) are invisible unless we
# add them back. Without this, notify() below silently found no launchpad and
# every outage alert no-opped — how the 2026-08-02..06 M2 outage went unreported.
PATH="$HOME_DIR/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
M2_HOST="${M2_HOST:-10.10.10.2}"
# A SECOND path to M2 (Tailscale), used only to tell "M2 is asleep/off" apart from "M2 is fine
# but the private link is down". The 2026-08-17 incident: the Thunderbolt cable dropped while M2
# sat awake with 87 days uptime, and this watchdog reported "likely asleep/off; manual wake may
# be needed" — sending the operator to check the machine instead of the cable. WoL cannot fix a
# cable, so the distinction decides both the advice and whether recovery is worth attempting.
M2_ALT_HOST="${M2_ALT_HOST-100.71.251.23}"   # M2 on Tailscale (node "ai-inference"); empty disables
M2_ALT_PORT="${M2_ALT_PORT:-22}"              # sshd — reachable regardless of the model servers
read -r -a PORTS <<< "${M2_PORTS:-8002 8003}"
read -r -a METER_PORTS <<< "${METER_PORTS:-9002 9003 9004 9006}"  # required local meter routes, including MMR GLM and local review
METER_LABEL="${METER_LABEL:-com.localai.dashboard.meter}"
# Probes send this as their API key so the meter attributes them to a named client instead of
# lumping them in with real traffic as 'unknown'. The meter treats any safe identifier as a label.
WATCHDOG_KEY="${WATCHDOG_KEY:-watchdog}"
UID_NUM="$(id -u)"
LOG="${M2_WATCHDOG_LOG:-$HOME_DIR/ai/logs/m2-watchdog.log}"
STATE="${M2_WATCHDOG_STATE:-$HOME_DIR/ai/logs/m2-watchdog.state}"
COOLDOWN="${M2_RECOVER_COOLDOWN:-300}"   # min seconds between recovery attempts (anti-thrash)
DRYRUN="${M2_WATCHDOG_DRYRUN:-0}"
mkdir -p "$(dirname "$LOG")"

ts()   { date "+%Y-%m-%dT%H:%M:%S%z"; }
logln() { printf "%s  %s\n" "$(ts)" "$1" >> "$LOG"; }
# A watchdog that cannot raise an alarm is worse than none, so a notify that
# cannot be delivered is recorded in the log rather than swallowed.
notify() {
  if command -v launchpad >/dev/null 2>&1; then
    launchpad notify "$1" >/dev/null 2>&1 || logln "  NOTIFY FAILED (launchpad error): $1"
  else
    logln "  NOTIFY FAILED (launchpad not on PATH): $1"
  fi
}

probe() {  # 0 iff every worker port is reachable
  local p
  for p in "${PORTS[@]}"; do
    nc -z -G 3 "$M2_HOST" "$p" >/dev/null 2>&1 || return 1
  done
  return 0
}

m2_alive_via_alt() {  # 0 iff M2 answers on its second path → the machine is up, only the link is down
  [ -n "$M2_ALT_HOST" ] || return 1
  nc -z -G 3 "$M2_ALT_HOST" "$M2_ALT_PORT" >/dev/null 2>&1
}

probe_meter() {  # 0 iff the local meter can actually PROXY to each M2 worker (HTTP 200), not just M2 being reachable
  command -v curl >/dev/null 2>&1 || return 0   # no curl → can't check; don't false-trigger a restart
  local mp code
  for mp in "${METER_PORTS[@]}"; do
    code="$(curl -s -m 5 -o /dev/null -w '%{http_code}' \
      -H "Authorization: Bearer $WATCHDOG_KEY" "http://127.0.0.1:$mp/v1/models" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] || return 1
  done
  return 0
}

# --- Orchestrator (M1, local) wedge detection ---
# Probe THROUGH the meter (:9001), not the model server (:8001), so the completion this generates
# is visible in the dashboard like any other request. The meter rewrites the model id to whatever
# :8001 actually serves, so ORCH_MODEL below only has to be non-empty.
ORCH_URL="${ORCH_URL:-http://127.0.0.1:9001}"
ORCH_LABEL="${ORCH_LABEL:-com.localai.orchestrator}"
ORCH_PROBE_TIMEOUT="${ORCH_PROBE_TIMEOUT:-30}"
ORCH_BAD_LIMIT="${ORCH_BAD_LIMIT:-2}"        # consecutive wedged probes before the (expensive) 35B reload
# Seconds between completion probes. launchd fires this script every 60s, but a real 35B generation
# every minute is 1,440 pointless inferences a day; at 300s it is ~288, and a wedge still surfaces
# within ORCH_BAD_LIMIT x this interval (~10 min).
ORCH_PROBE_INTERVAL="${ORCH_PROBE_INTERVAL:-300}"
ORCH_BUSY_WINDOW="${ORCH_BUSY_WINDOW:-180}"  # a real orchestrator completion this recent => busy, not wedged
ORCH_STATE="${ORCH_STATE:-$HOME_DIR/ai/logs/m2-watchdog-orch.state}"
TELEMETRY_DB="${TELEMETRY_DB:-$HOME_DIR/ai/dashboard/telemetry.db}"

# To mlx_lm.server the `model` field is a LOAD INSTRUCTION, not a selector: send a path it is not
# already serving and it loads a SECOND copy of that model. This probe used to hardcode the bf16
# orchestrator (65 GB) while the stack actually runs mixed9 (38 GB), and only the meter's
# METER_ORCH_MODEL pin stopped it from triggering that load. Ask the endpoint what it serves.
# Same rule as scripts/smoke-test-endpoints.sh and the dashboard's pickChatModel().
endpoint_model() {  # $1 = meter base url; prints the model id that endpoint actually serves
  # Split the JSON on commas/braces so each "id" lands on its own line, then take the first id that
  # looks like a local model path.
  curl -s -m 5 -H "Authorization: Bearer $WATCHDOG_KEY" "$1/v1/models" 2>/dev/null \
    | tr ',{}' '\n' \
    | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\(\/[^"]*\)".*/\1/p' \
    | head -1
}

probe_endpoint() {  # $1 = meter base url; 0 iff it COMPLETES a tiny request (real inference, not just /models)
  command -v curl >/dev/null 2>&1 || return 0  # no curl → can't check; don't false-trigger
  local base="$1" code model
  model="${2:-$(endpoint_model "$1")}"
  # No id means /v1/models itself did not answer (meter restarting, say). That is not evidence the
  # endpoint is wedged, and guessing an id here is exactly the second-copy bug above.
  [ -n "$model" ] || return 0
  code="$(curl -s -m "$ORCH_PROBE_TIMEOUT" -o /dev/null -w '%{http_code}' "$base/v1/chat/completions" \
    -H 'content-type: application/json' \
    -H "Authorization: Bearer $WATCHDOG_KEY" \
    --data "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":1}" 2>/dev/null || echo 000)"
  [ "$code" = "200" ]
}

orch_model()        { if [ -n "${ORCH_MODEL:-}" ]; then printf '%s' "$ORCH_MODEL"; else endpoint_model "$ORCH_URL"; fi; }
probe_orchestrator() { probe_endpoint "$ORCH_URL" "$(orch_model)"; }

# --- Orchestrator crash detection straight from the server log ---
# mlx-lm leaks live Metal buffer descriptors while decoding and eventually throws
#   RuntimeError: [metal::malloc] Resource limit (499000) exceeded.
# which kills the server's single generation thread. 499000 is a COUNT of live Metal buffers, not
# bytes — the machine is not out of memory when this fires. The process survives and keeps answering
# /v1/models with 200 while every completion hangs forever, so the completion probe below only
# notices after ORCH_BAD_LIMIT x ORCH_PROBE_INTERVAL (~10 min), and `orchestrator_served_recently`
# can stretch that further by reading a pre-crash success as "busy, not wedged". That is how
# 2026-08-24 cost ~36 minutes across four crashes. The traceback is unambiguous and free to grep
# every tick, which brings recovery down to one tick.
# Upstream: ml-explore/mlx-lm issues #831, #1185, #1332 — all open, no released fix, so restarting
# is the only lever we have. Drop this block once a release fixes the leak.
ORCH_LOG="${ORCH_LOG:-$HOME_DIR/ai/logs/orchestrator.log}"
ORCH_CRASH_RE="${ORCH_CRASH_RE:-Exception in thread Thread-1 \(_generate\)|metal::malloc\] Resource limit}"

orch_crash_in_new_log() {  # 0 iff the generation thread died in log written since the last tick
  [ -f "$ORCH_LOG" ] || return 1
  local size seen
  size="$(wc -c < "$ORCH_LOG" 2>/dev/null | tr -d ' ')" || return 1
  case "$size" in ''|*[!0-9]*) return 1 ;; esac
  # First run, or the log was rotated/truncated: adopt the current end and scan nothing. Without
  # this the first tick after deploying would restart on crashes that were recovered hours ago.
  case "${orch_log_pos:-}" in
    ''|*[!0-9]*) orch_log_pos="$size"; return 1 ;;
  esac
  if [ "$orch_log_pos" -gt "$size" ]; then orch_log_pos="$size"; return 1; fi
  seen="$orch_log_pos"
  orch_log_pos="$size"
  [ "$size" -gt "$seen" ] || return 1
  tail -c "+$(( seen + 1 ))" "$ORCH_LOG" 2>/dev/null | grep -qE "$ORCH_CRASH_RE"
}

# --- M2 worker wedge detection ---
# The developer and reviewer servers hit the SAME mlx Metal-buffer crash described above, and their
# generation threads die the same way while /v1/models keeps returning 200. On 2026-08-24/25 both
# wedged overnight and served nothing for seven hours (126 failed requests) because this watchdog
# only ever looked at the orchestrator.
#
# Two independent checks, because each misses what the other catches:
#
#   1. A real completion probe through the meter, on its own interval. This is the only check that
#      works while M2 is IDLE. Before 2026-08-25 there was none: M2's health was read purely from
#      whatever the user's own traffic happened to reveal, so a wedge on an unused endpoint sat
#      undiscovered until they next tried it. It also keeps the dashboard honest — the orchestrator
#      always looked green only because its probe kept its "last seen" fresh, while healthy M2
#      endpoints decayed to grey after six idle hours and read as down.
#   2. Telemetry from real client traffic: an upstream carrying several failures and NO successes
#      over the window is wedged by definition. Catches wedges a one-token probe is too small to
#      trip — a server that answers "ping" but dies on a 30k-token prompt.
#
# Only the restart crosses to M2, and it needs no sudo — the workers are LaunchDaemons with
# KeepAlive SuccessfulExit=false, so killing the process makes launchd start a fresh one.
#
# Spec is name:mlx_port:meter_port. The mlx port identifies the process to kill ON M2; the meter
# port is what we probe, so the probe lands in telemetry like any other request and the dashboard
# row for that upstream stays current.
M2_WORKERS="${M2_WORKERS:-developer:8002:9002 reviewer:8003:9003}"
M2_WEDGE_WINDOW="${M2_WEDGE_WINDOW:-900}"      # seconds of history the telemetry verdict is based on
M2_WEDGE_FAILURES="${M2_WEDGE_FAILURES:-3}"    # failures needed, alongside zero successes
M2_PROBE_INTERVAL="${M2_PROBE_INTERVAL:-300}"  # a real generation, so not every 60s tick
M2_BAD_LIMIT="${M2_BAD_LIMIT:-2}"              # consecutive failed probes before the expensive reload
M2_SSH_HOST="${M2_SSH_HOST:-m2}"               # ~/.ssh/config alias; key auth, never prompts
WORKER_STATE="${WORKER_STATE:-$HOME_DIR/ai/logs/m2-watchdog-workers.state}"

worker_served_recently() {  # $1 = upstream; 0 iff real client traffic succeeded within the busy window
  command -v sqlite3 >/dev/null 2>&1 || return 1
  [ -f "$TELEMETRY_DB" ] || return 1
  local last
  last="$(sqlite3 "$TELEMETRY_DB" \
    "SELECT COALESCE(MAX(ts),0) FROM requests
      WHERE upstream='$1' AND error_class='ok' AND client<>'$WATCHDOG_KEY';" 2>/dev/null || echo 0)"
  case "$last" in ''|*[!0-9]*) last=0 ;; esac
  [ $(( now * 1000 - last )) -lt $(( ORCH_BUSY_WINDOW * 1000 )) ]
}

worker_wedged() {  # $1 = upstream name; 0 iff the window holds chat failures and no successes
  command -v sqlite3 >/dev/null 2>&1 || return 1
  [ -f "$TELEMETRY_DB" ] || return 1
  local row fails succs
  # One row of "fails|successes" so a single query decides it. Restricted to kind='chat' because
  # only a real completion proves the generation thread is alive; /v1/models answers either way.
  row="$(sqlite3 "$TELEMETRY_DB" \
    "SELECT COALESCE(SUM(error_class<>'ok'),0)||'|'||COALESCE(SUM(error_class='ok'),0)
       FROM requests
      WHERE upstream='$1' AND kind='chat'
        AND ts >= $(( (now - M2_WEDGE_WINDOW) * 1000 ));" 2>/dev/null)" || return 1
  fails="${row%%|*}"; succs="${row##*|}"
  case "${fails}${succs}" in ''|*[!0-9]*) return 1 ;; esac
  [ "$succs" -eq 0 ] && [ "$fails" -ge "$M2_WEDGE_FAILURES" ]
}

# --- Keep M2's checkout current ---
# M2 runs its own clone of this repo at ~/ai/local-ai-stack and nothing ever pulls it. On
# 2026-08-25 it was found 10 commits behind, so a launcher fix landed on 2026-08-25 was still
# inert there eight days after the last change — invisible until a restart was expected to pick
# something up and did not. Once a day is plenty; this is drift, not an outage.
#
# --ff-only on purpose: if M2's checkout has diverged (someone edited a script there), this stops
# and says so rather than merging or discarding their work. Pulling never restarts anything either
# — a launcher change only takes effect on the next model reload, which is a multi-minute outage
# and the operator's call to schedule. When a launcher does change, say so.
M2_SYNC_INTERVAL="${M2_SYNC_INTERVAL:-86400}"
M2_REPO_DIR="${M2_REPO_DIR:-ai/local-ai-stack}"   # relative to M2's home
M2_SYNC_STATE="${M2_SYNC_STATE:-$HOME_DIR/ai/logs/m2-watchdog-sync.state}"

# Single-quoted so M1's shell expands nothing; __REPO__ is substituted below.
M2_SYNC_REMOTE='
cd "$HOME/__REPO__" 2>/dev/null || { echo NOREPO; exit 0; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo NOTGIT; exit 0; }
before=$(git rev-parse --short HEAD)
git pull -q --ff-only origin main >/dev/null 2>&1 || { echo PULLFAILED; exit 0; }
after=$(git rev-parse --short HEAD)
[ "$before" = "$after" ] && { echo "CURRENT $after"; exit 0; }
echo "MOVED $before $after"
git diff --name-only "$before" "$after" | grep "^scripts/start-" || true
'

sync_m2_checkout() {  # prints the remote report; non-zero only if ssh itself failed
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$M2_SSH_HOST" \
    "${M2_SYNC_REMOTE//__REPO__/$M2_REPO_DIR}" 2>/dev/null
}

restart_m2_worker() {  # $1 = port of the wedged mlx server on M2
  # mlx_lm[.]server, not mlx_lm.server: the bracket keeps the pattern from matching the remote shell
  # that is running pkill, which carries the pattern text in its own command line.
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$M2_SSH_HOST" \
    "pkill -f 'mlx_lm[.]server.*--port $1'" >> "$LOG" 2>&1
}

orchestrator_served_recently() {  # 0 iff a successful orchestrator completion is in telemetry within the window
  command -v sqlite3 >/dev/null 2>&1 || return 1  # can't tell → treat as not-recent, lean on the probe
  [ -f "$TELEMETRY_DB" ] || return 1
  local last
  last="$(sqlite3 "$TELEMETRY_DB" "SELECT COALESCE(MAX(ts),0) FROM requests WHERE upstream='orchestrator' AND error_class='ok' AND client<>'$WATCHDOG_KEY';" 2>/dev/null || echo 0)"
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
orch_bad=0; orch_last_recover=0; orch_last_probe=0; orch_log_pos=""
# shellcheck disable=SC1090
[ -f "$ORCH_STATE" ] && . "$ORCH_STATE" 2>/dev/null || true
write_orch() {
  printf 'orch_bad=%s\norch_last_recover=%s\norch_last_probe=%s\norch_log_pos=%s\n' \
    "$1" "$2" "${3:-$orch_last_probe}" "${4:-${orch_log_pos:-}}" > "$ORCH_STATE"
}

# Checked every tick (reading a few log bytes is free), and BEFORE the completion probe: a crashed
# generation thread is proof of a wedge, so there is nothing to confirm by waiting.
if orch_crash_in_new_log; then
  if [ $(( now - orch_last_recover )) -lt "$COOLDOWN" ]; then
    logln "  orchestrator generation thread crashed (mlx Metal buffer limit) — within ${COOLDOWN}s cooldown, no action this tick"
    write_orch "$orch_bad" "$orch_last_recover"
  elif [ "$DRYRUN" = "1" ]; then
    logln "  [dry-run] orchestrator generation thread crashed (mlx Metal buffer limit) — would restart $ORCH_LABEL"
    write_orch 0 "$now"
  else
    logln "  orchestrator CRASHED — mlx generation thread died on the Metal buffer limit; restarting $ORCH_LABEL"
    launchctl kickstart -k "gui/$UID_NUM/$ORCH_LABEL" >> "$LOG" 2>&1 || logln "  orchestrator kickstart failed"
    notify "Orchestrator crashed 🔧 — mlx hit its Metal buffer limit; restarted (reloads the 35B)"
    write_orch 0 "$now"
  fi
elif [ $(( now - orch_last_probe )) -lt "$ORCH_PROBE_INTERVAL" ]; then
  # Not due yet — the probe is real inference, so it runs on its own interval, not every tick.
  # Still persist state so the log scan position advances and the next tick reads only new bytes.
  write_orch "$orch_bad" "$orch_last_recover"
elif { orch_last_probe="$now"; probe_orchestrator; }; then
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

  # Individual workers can be wedged while the machine and its ports are perfectly reachable — the
  # mlx generation thread dies but the socket stays open. Only checked here, inside the reachable
  # branch: when M2 is down every request fails too, and that is a link problem, not a wedge.
  # shellcheck disable=SC1090
  [ -f "$WORKER_STATE" ] && . "$WORKER_STATE" 2>/dev/null || true
  worker_state_out=""
  for worker_spec in $M2_WORKERS; do
    IFS=: read -r worker_name worker_port worker_meter <<< "$worker_spec"
    worker_kick_var="kick_$worker_name"; worker_probe_var="probe_$worker_name"; worker_bad_var="bad_$worker_name"
    worker_last="${!worker_kick_var:-0}"
    worker_last_probe="${!worker_probe_var:-0}"
    worker_bad="${!worker_bad_var:-0}"
    for _v in worker_last worker_last_probe worker_bad; do
      case "${!_v}" in ''|*[!0-9]*) eval "$_v=0" ;; esac
    done
    worker_is_wedged=0

    # (1) Real completion probe. The only check that works while M2 is idle, and the thing that
    #     keeps this upstream's dashboard row from decaying to grey and reading as down.
    if [ -n "$worker_meter" ] && [ $(( now - worker_last_probe )) -ge "$M2_PROBE_INTERVAL" ]; then
      worker_last_probe="$now"
      if probe_endpoint "http://127.0.0.1:$worker_meter"; then
        [ "$worker_bad" -gt 0 ] && { logln "M2 $worker_name RECOVERED — serving completions"; notify "M2 $worker_name recovered ✅"; }
        worker_bad=0
      elif worker_served_recently "$worker_name"; then
        # mlx serializes, so a busy server times out a probe. Real traffic succeeding recently is
        # proof it is alive; same reasoning as the orchestrator path above.
        logln "  M2 $worker_name completion probe timed out but it served recently — busy, not wedged"
        worker_bad=0
      else
        worker_bad=$(( worker_bad + 1 ))
        if [ "$worker_bad" -ge "$M2_BAD_LIMIT" ]; then
          worker_is_wedged=1
        else
          logln "  M2 $worker_name completion probe failing (x$worker_bad) — watching before the (expensive) reload"
        fi
      fi
    fi

    # (2) Telemetry from real client traffic — catches a wedge too big for a one-token probe to trip.
    worker_wedged "$worker_name" && worker_is_wedged=1

    if [ "$worker_is_wedged" = "1" ] && [ $(( now - worker_last )) -ge "$COOLDOWN" ]; then
      if [ "$DRYRUN" = "1" ]; then
        logln "  [dry-run] M2 $worker_name wedged — would restart its :$worker_port server"
      else
        logln "  M2 $worker_name WEDGED — killing the :$worker_port server (launchd KeepAlive reloads it)"
        if restart_m2_worker "$worker_port"; then
          notify "M2 $worker_name unwedged 🔧 — mlx had hung; restarted (reloads the model)"
        else
          logln "  could not reach $M2_SSH_HOST to restart $worker_name — check ssh key auth"
        fi
      fi
      worker_last="$now"; worker_bad=0
    fi
    worker_state_out="${worker_state_out}${worker_kick_var}=${worker_last}
${worker_probe_var}=${worker_last_probe}
${worker_bad_var}=${worker_bad}
"
  done
  printf '%s' "$worker_state_out" > "$WORKER_STATE"

  # Pull M2's checkout at most once a day. Only reached when M2 is up, which is exactly when a
  # pull can succeed.
  last_sync=0
  # shellcheck disable=SC1090
  [ -f "$M2_SYNC_STATE" ] && . "$M2_SYNC_STATE" 2>/dev/null || true
  case "$last_sync" in ''|*[!0-9]*) last_sync=0 ;; esac
  if [ $(( now - last_sync )) -ge "$M2_SYNC_INTERVAL" ]; then
    if [ "$DRYRUN" = "1" ]; then
      logln "  [dry-run] M2 checkout sync is due — would pull $M2_REPO_DIR on $M2_SSH_HOST"
    else
      sync_report="$(sync_m2_checkout)" || sync_report="SSHFAILED"
      case "${sync_report%%$'\n'*}" in
        MOVED*)
          # First line is "MOVED <before> <after>"; any further lines are changed launcher scripts.
          read -r _moved before after <<< "${sync_report%%$'\n'*}"
          changed="$(printf '%s' "$sync_report" | sed -n '2,$p' | tr '\n' ' ')"
          logln "  M2 checkout updated ${before}..${after}${changed:+ (launchers changed: $changed)}"
          # Only worth interrupting the operator when a restart is actually needed to apply it.
          [ -n "$changed" ] && notify "M2 launchers updated 🔄 — restart its workers to apply: $changed"
          ;;
        CURRENT*)   : ;;               # already up to date, every other day — not worth a log line
        PULLFAILED) logln "  M2 checkout would not fast-forward — it has local changes or has diverged; leaving it alone"
                    notify "M2 checkout is stuck 🔧 — it will not fast-forward; look at ~/$M2_REPO_DIR on M2" ;;
        NOREPO|NOTGIT) logln "  M2 has no git checkout at ~/$M2_REPO_DIR — nothing to sync" ;;
        SSHFAILED)  logln "  could not reach $M2_SSH_HOST to sync its checkout" ;;
        *)          logln "  unexpected reply from the M2 checkout sync: ${sync_report:-<empty>}" ;;
      esac
    fi
    printf 'last_sync=%s\n' "$now" > "$M2_SYNC_STATE"
  fi

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

# Machine down, or just the private link? The answer changes the advice entirely.
LINK_ONLY=0
if m2_alive_via_alt; then
  LINK_ONLY=1
  logln "  M2 itself is ALIVE via $M2_ALT_HOST:$M2_ALT_PORT — the machine is up; the $M2_HOST link is down"
fi

if [ $((now - last_recover)) -lt "$COOLDOWN" ]; then
  logln "  within ${COOLDOWN}s recovery cooldown — no action this tick"
  write_state down "$last_recover"
  exit 0
fi

if [ "$prev_status" != "down" ]; then
  if [ "$LINK_ONLY" = "1" ]; then
    notify "M2 link down 🔌 — M2 is awake but $M2_HOST is unreachable; check the Thunderbolt cable"
  else
    notify "M2 worker dropped ⚠️ — attempting auto-recovery"
  fi
fi

# 1) best-effort wake — pointless when M2 is provably awake
if [ "$LINK_ONLY" = "1" ]; then
  logln "  skipping Wake-on-LAN — M2 is awake; WoL cannot fix a down link"
elif [ "$DRYRUN" = "1" ]; then
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
elif [ "$LINK_ONLY" = "1" ]; then
  logln "  STILL DOWN — M2 is awake via $M2_ALT_HOST but $M2_HOST is unreachable; check the Thunderbolt cable/bridge0"
  notify "M2 link still down 🔌 — M2 is awake; check the Thunderbolt cable"; write_state down "$now"
else
  logln "  STILL DOWN after WoL + meter restart — likely asleep/off; manual wake may be needed"
  notify "M2 still down ❌ — may need a manual wake"; write_state down "$now"
fi
exit 0
