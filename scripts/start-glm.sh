#!/usr/bin/env bash
set -euo pipefail

# Machine 1 local GLM-5.2 (4-bit MLX, ~418 GB resident). Replaces the paid z.ai cloud endpoint the
# meter fronts on :9004. Mirrors start-orchestrator.sh's preflight: exit 0 (not 1) if our server is
# already answering, so launchd never treats "already running" as a crash.
#
# REQUIRES a raised GPU wired-memory ceiling — the default (~75% of RAM, ~384 GB) is below this
# model. See configs/launchd/com.localai.wiredlimit.plist. Verify: sysctl iogpu.wired_limit_mb

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
source "$REPO_DIR/.venv/bin/activate"
mkdir -p "$HOME/ai/logs"

MODEL="${GLM_MODEL_PATH:-$HOME/ai/models/glm-5.2-4bit}"
PORT="${GLM_PORT:-8005}"  # 8004 is reserved for the experimental MTP lane (docs/EXPERIMENTAL_MTP.md)
HOST="${GLM_HOST:-127.0.0.1}"
PROMPT_CACHE_SIZE="${PROMPT_CACHE_SIZE:-10}"
PROMPT_CACHE_BYTES="${PROMPT_CACHE_BYTES:-16GB}"

if curl -s --max-time 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | grep -q '"data"'; then
  echo "An mlx_lm server is already responding on $HOST:$PORT — not starting a duplicate."
  exit 0
fi

WIRED=$(sysctl -n iogpu.wired_limit_mb 2>/dev/null || echo 0)
if [ "$WIRED" -eq 0 ]; then
  echo "WARNING: iogpu.wired_limit_mb is 0 (macOS default ≈75% of RAM). GLM-5.2 4-bit needs ~418 GB"
  echo "         resident and will likely fail to load. Install com.localai.wiredlimit.plist first."
fi

echo "Starting Machine 1 GLM:"
echo "  Model: $MODEL"
echo "  URL:   http://$HOST:$PORT/v1"
echo "Log:   $HOME/ai/logs/glm.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --prompt-cache-size "$PROMPT_CACHE_SIZE" \
  --prompt-cache-bytes "$PROMPT_CACHE_BYTES" \
  >> "$HOME/ai/logs/glm.log" 2>&1
