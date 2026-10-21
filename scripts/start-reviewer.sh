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
# Same Qwen3.8-27B oQ8e-mtp weights as the developer, through a reviewer-named symlink so the model
# id reads `reviewer-...`. MiMo-V2.6-Flash (a different family) was measured 2026-10-21 and lost on
# the deciding number: 83% recall vs the 27B's 94% (dashboard repo, eval/results/2026-10-21-mimo-
# reviewer). Set OMLX_REVIEW_MODEL to trial another candidate.
export ROLE=reviewer
export PORT="${REVIEW_PORT:-8003}"
export HOST="${WORKER_HOST:-10.10.10.2}"
export MODEL="${OMLX_REVIEW_MODEL:-$HOME/ai/models/reviewer-qwen38-27b-oq8e-mtp}"
exec "$HERE/omlx-serve.sh"
