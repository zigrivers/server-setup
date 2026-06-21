#!/usr/bin/env bash
# Usage-ping wrapper for agent CLIs that MMR invokes but that DON'T go through the meter
# (codex/grok/antigravity → their own clouds). Fires a fire-and-forget POST to the dashboard so the
# call is counted, then runs the real CLI untouched. It must NEVER block, delay, or fail the CLI.
#
#   track-cli <client-label> <real-cmd> [args...]
# e.g. as an MMR channel command:  track-cli codex codex exec
#
# Env: DASHBOARD_INGEST (default http://127.0.0.1:9100).
set -uo pipefail

LABEL="${1:?usage: track-cli <label> <cmd> [args...]}"; shift
[ "$#" -gt 0 ] || { echo "track-cli: no command to run" >&2; exit 1; }

INGEST="${DASHBOARD_INGEST:-http://127.0.0.1:9100}"
# Best-effort, time-boxed, errors swallowed: a down/slow meter can never affect the real CLI.
curl -s -m 2 -X POST "$INGEST/usage" -H 'content-type: application/json' \
  --data "{\"client\":\"$LABEL\"}" >/dev/null 2>&1 || true

exec "$@"
