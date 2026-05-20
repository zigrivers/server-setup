#!/usr/bin/env bash
set -euo pipefail

for port in "${DEV_PORT:-8002}" "${REVIEW_PORT:-8003}" "${MTP_PORT:-8004}"; do
  PIDS="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
  if [ -n "$PIDS" ]; then
    echo "Stopping PIDs on port $port: $PIDS"
    kill $PIDS
  else
    echo "No process listening on port $port."
  fi
done
