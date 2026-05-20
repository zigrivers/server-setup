#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
source "$REPO_DIR/.venv/bin/activate"
mkdir -p "$HOME/ai/logs"

MODEL="${ORCH_MODEL_PATH:-$HOME/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16}"
PORT="${ORCH_PORT:-8001}"
HOST="${ORCH_HOST:-127.0.0.1}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already listening on port $PORT:"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  exit 1
fi

echo "Starting Machine 1 Orchestrator:"
echo "  Model: $MODEL"
echo "  URL:   http://$HOST:$PORT/v1"

nohup mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  > "$HOME/ai/logs/orchestrator.log" 2>&1 &

echo "Started. Log: $HOME/ai/logs/orchestrator.log"
