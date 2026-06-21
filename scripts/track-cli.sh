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

# Exec the REAL binary with the cli-shims dir stripped from PATH, so this (MMR-driven) call is NOT
# also counted by the PATH shim — the shim only handles direct, non-MMR calls. Exactly one ping/call.
cmd="$1"; shift
shim_dir="$HOME/.local/cli-shims"
clean_path="$(printf %s ":$PATH:" | sed "s#:${shim_dir}:#:#g" | sed 's/^://; s/:$//')"
real="$(PATH="$clean_path" command -v "$cmd" 2>/dev/null || echo "$cmd")"
exec "$real" "$@"
