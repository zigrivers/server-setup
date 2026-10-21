#!/usr/bin/env bash
# Machine 1 Orchestrator launcher (launchd: com.localai.orchestrator).
# Default server is oMLX (scripts/omlx-serve.sh). Rollback to mlx_lm.server + the #1845 shim with
#   LOCAL_AI_SERVER=mlx_lm  (scripts/start-orchestrator-mlx_lm.sh, unchanged).
set -euo pipefail
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
if [ "${LOCAL_AI_SERVER:-omlx}" = "mlx_lm" ]; then
  exec "$HERE/start-orchestrator-mlx_lm.sh"
fi
# Base Qwen3.6-35B-A3B weights (not the abliterated "heretic" build) with the MTP head kept: oMLX's
# oQ4e quant, ~4.7 bits/weight, 20 GB. Measured 2026-10-21: 90 tok/s decode on M3 Ultra.
export ROLE=orchestrator
export PORT="${ORCH_PORT:-8001}"
export HOST="${ORCH_HOST:-127.0.0.1}"
export MODEL="${OMLX_ORCH_MODEL:-$HOME/ai/models/orchestrator-qwen36-35b-a3b-oq4e-mtp}"
exec "$HERE/omlx-serve.sh"
