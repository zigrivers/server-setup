#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
source "$REPO_DIR/.venv/bin/activate"
mkdir -p "$HOME/ai/logs"

MODEL="${ORCH_MODEL_PATH:-$HOME/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16}"
PORT="${ORCH_PORT:-8001}"
HOST="${ORCH_HOST:-127.0.0.1}"
# Prompt/prefix KV cache: explicit + byte-bounded so it can't grow unbounded (mlx_lm default is
# size 10, bytes UNbounded). "8GB" is parsed by mlx_lm's _parse_size (decimal GB). Env-tunable.
PROMPT_CACHE_SIZE="${PROMPT_CACHE_SIZE:-10}"
PROMPT_CACHE_BYTES="${PROMPT_CACHE_BYTES:-8GB}"

# Abort only if OUR OpenAI-compatible server is already answering here (avoid a duplicate).
# A bare lsof check false-positives on unrelated listeners that may share the port on another
# interface (e.g. a Docker/OrbStack container publishing 0.0.0.0:PORT), which would crash-loop
# under launchd. Distinguish by probing /v1/models for a real model list. Exit 0 (not 1) so
# launchd never treats "already running" as a crash.
if curl -s --max-time 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | grep -q '"data"'; then
  echo "An mlx_lm server is already responding on $HOST:$PORT — not starting a duplicate."
  exit 0
fi

echo "Starting Machine 1 Orchestrator:"
echo "  Model: $MODEL"
echo "  URL:   http://$HOST:$PORT/v1"

echo "Log: $HOME/ai/logs/orchestrator.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --prompt-cache-size "$PROMPT_CACHE_SIZE" \
  --prompt-cache-bytes "$PROMPT_CACHE_BYTES" \
  >> "$HOME/ai/logs/orchestrator.log" 2>&1
