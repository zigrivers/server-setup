#!/usr/bin/env bash
# Machine 2 Reviewer launcher (launchd: com.localai.reviewer).
# Default server is oMLX (scripts/omlx-serve.sh). Rollback to mlx_lm.server + the #1845 shim with
#   LOCAL_AI_SERVER=mlx_lm  (scripts/start-reviewer-mlx_lm.sh, unchanged).
set -euo pipefail
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
if [ -f "$REPO_DIR/.env" ]; then set -a; source "$REPO_DIR/.env"; set +a; fi
if [ "${LOCAL_AI_SERVER:-omlx}" = "mlx_lm" ]; then
  exec "$HERE/start-reviewer-mlx_lm.sh"
fi
# The reviewer is a DIFFERENT model family from the developer on purpose (a reviewer sharing the
# author's weights shares its blind spots): MiMo-V2.6-Flash, 309B total / 15B active, 156 GB.
# Set OMLX_REVIEW_MODEL to swap it (e.g. back to the 27B oQ8e-mtp build while MiMo is evaluated).
export ROLE=reviewer
export PORT="${REVIEW_PORT:-8003}"
export HOST="${WORKER_HOST:-10.10.10.2}"
export MODEL="${OMLX_REVIEW_MODEL:-$HOME/ai/models/reviewer-mimo-v2.6-flash-mxfp4-q8}"
exec "$HERE/omlx-serve.sh"
