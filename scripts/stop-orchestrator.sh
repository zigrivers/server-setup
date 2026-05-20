#!/usr/bin/env bash
set -euo pipefail

PORT="${ORCH_PORT:-8001}"
PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN || true)"

if [ -z "$PIDS" ]; then
  echo "No process listening on port $PORT."
  exit 0
fi

echo "Stopping Orchestrator PIDs: $PIDS"
kill $PIDS
