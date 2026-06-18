#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
source "$REPO_DIR/.venv/bin/activate"
mkdir -p "$HOME/ai/logs"

if [ -f "$REPO_DIR/.env" ]; then
  set -a; source "$REPO_DIR/.env"; set +a
fi

HOST="${WORKER_HOST:-10.10.10.2}"
PORT="${DEV_PORT:-8002}"
MODEL="${DEV_MODEL_PATH:-$HOME/ai/models/developer-qwen36-27b-heretic2-mixed94}"
# Explicit, byte-bounded prompt/prefix KV cache (mlx_lm default: size 10, bytes unbounded).
PROMPT_CACHE_SIZE="${PROMPT_CACHE_SIZE:-10}"
PROMPT_CACHE_BYTES="${PROMPT_CACHE_BYTES:-12GB}"

# Abort only if OUR mlx_lm server is already answering here (avoid a duplicate). A bare lsof
# check false-positives on unrelated listeners sharing the port (e.g. a Docker container on
# 0.0.0.0:PORT), which would crash-loop under launchd. Exit 0 (not 1) so "already running" isn't
# treated as a crash.
if curl -s --max-time 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | grep -q '"data"'; then
  echo "An mlx_lm server is already responding on $HOST:$PORT — not starting a duplicate."
  exit 0
fi

echo "Starting Developer on $HOST:$PORT (model: $MODEL)"
echo "Log: $HOME/ai/logs/developer.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --prompt-cache-size "$PROMPT_CACHE_SIZE" \
  --prompt-cache-bytes "$PROMPT_CACHE_BYTES" \
  >> "$HOME/ai/logs/developer.log" 2>&1
