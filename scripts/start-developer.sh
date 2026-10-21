#!/usr/bin/env bash
# Machine 2 Developer launcher (launchd: com.localai.developer).
# Default server is oMLX (scripts/omlx-serve.sh). Rollback to mlx_lm.server + the #1845 shim with
#   LOCAL_AI_SERVER=mlx_lm  (scripts/start-developer-mlx_lm.sh, unchanged).
set -euo pipefail
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
if [ -f "$REPO_DIR/.env" ]; then set -a; source "$REPO_DIR/.env"; set +a; fi
if [ "${LOCAL_AI_SERVER:-omlx}" = "mlx_lm" ]; then
  exec "$HERE/start-developer-mlx_lm.sh"
fi
# Qwen3.8-27B 8-bit with the MTP head kept (oMLX oQ8e build, 28 GB). Same weights quality as the
# mlx-community 8-bit; MTP measured 2026-10-21: 47 tok/s vs 20 without.
export ROLE=developer
export PORT="${DEV_PORT:-8002}"
export HOST="${WORKER_HOST:-10.10.10.2}"
export MODEL="${OMLX_DEV_MODEL:-$HOME/ai/models/developer-qwen38-27b-oq8e-mtp}"
exec "$HERE/omlx-serve.sh"
