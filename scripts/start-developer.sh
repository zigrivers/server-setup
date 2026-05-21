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

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already listening on port $PORT:"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  exit 1
fi

echo "Starting Developer on $HOST:$PORT (model: $MODEL)"
echo "Log: $HOME/ai/logs/developer.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  >> "$HOME/ai/logs/developer.log" 2>&1
