#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
source "$REPO_DIR/.venv/bin/activate"
mkdir -p "$HOME/ai/logs"

if [ -f "$REPO_DIR/.env" ]; then
  set -a; source "$REPO_DIR/.env"; set +a
fi

HOST="${WORKER_HOST:-10.10.10.2}"
PORT="${REVIEW_PORT:-8003}"
MODEL="${REVIEW_MODEL_PATH:-$HOME/ai/models/reviewer-qwen36-27b-heretic-bf16}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already listening on port $PORT:"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  exit 1
fi

echo "Starting Reviewer on $HOST:$PORT (model: $MODEL)"
echo "Log: $HOME/ai/logs/reviewer.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  >> "$HOME/ai/logs/reviewer.log" 2>&1
