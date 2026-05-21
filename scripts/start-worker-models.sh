#!/usr/bin/env bash
set -euo pipefail

# Run on Machine 2 / inference worker.
REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
source "$REPO_DIR/.venv/bin/activate"
mkdir -p "$HOME/ai/logs"

# Load .env for model path overrides (REVIEW_MODEL_PATH, DEV_MODEL_PATH, etc.)
if [ -f "$REPO_DIR/.env" ]; then
  set -a; source "$REPO_DIR/.env"; set +a
fi

HOST="${WORKER_HOST:-10.10.10.2}"
DEV_PORT="${DEV_PORT:-8002}"
REVIEW_PORT="${REVIEW_PORT:-8003}"
DEV_MODEL="${DEV_MODEL_PATH:-$HOME/ai/models/developer-qwen36-27b-heretic2-mixed94}"
REVIEW_MODEL="${REVIEW_MODEL_PATH:-$HOME/ai/models/reviewer-qwen36-27b-heretic-bf16}"

for port in "$DEV_PORT" "$REVIEW_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Something is already listening on port $port:"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN
    exit 1
  fi
done

echo "Starting Developer on $HOST:$DEV_PORT"
nohup mlx_lm.server \
  --model "$DEV_MODEL" \
  --host "$HOST" \
  --port "$DEV_PORT" \
  > "$HOME/ai/logs/developer.log" 2>&1 &

echo "Starting Reviewer on $HOST:$REVIEW_PORT"
nohup mlx_lm.server \
  --model "$REVIEW_MODEL" \
  --host "$HOST" \
  --port "$REVIEW_PORT" \
  > "$HOME/ai/logs/reviewer.log" 2>&1 &

echo "Started worker models."
echo "Developer log: $HOME/ai/logs/developer.log"
echo "Reviewer log:  $HOME/ai/logs/reviewer.log"
