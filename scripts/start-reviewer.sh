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
# NOTE: the authoritative model choice lives in .env (sourced above) as
# DEV_MODEL_PATH / REVIEW_MODEL_PATH. This default is only the fallback if .env is absent.
MODEL="${REVIEW_MODEL_PATH:-$HOME/ai/models/developer-qwen38-27b-8bit}"
# Explicit, byte-bounded prompt/prefix KV cache (mlx_lm default: size 10, bytes unbounded).
PROMPT_CACHE_SIZE="${PROMPT_CACHE_SIZE:-10}"
PROMPT_CACHE_BYTES="${PROMPT_CACHE_BYTES:-12GB}"
# Optional speculative decoding: set DRAFT_MODEL (a small model sharing this model's tokenizer).
# Off by default → zero behavior change. NOT for the MoE orchestrator; measure acceptance first.
DRAFT_ARGS=()
if [ -n "${DRAFT_MODEL:-}" ]; then
  DRAFT_ARGS=(--draft-model "$DRAFT_MODEL" --num-draft-tokens "${NUM_DRAFT_TOKENS:-3}")
fi

# mlx_lm.server's own --max-tokens default is 512, and it applies to any request that does not
# send max_tokens of its own. OpenCode and the Phase 8 enrichment script both send one, so this is
# a floor for everything else (curl probes, smoke tests, new clients) rather than a cap on them.
MAX_TOKENS="${MLX_MAX_TOKENS:-8192}"
# Chat-template arguments, passed to the model's Jinja template as JSON — this is how to set
# something like {"enable_thinking": false} for a whole endpoint instead of per request.
# UNSET BY DEFAULT ON PURPOSE: turning thinking off measured 89% -> 78% recall on the code-review
# eval, so it belongs on a bulk-classification lane, never on the reviewer or developer.
TEMPLATE_ARGS=()
if [ -n "${MLX_CHAT_TEMPLATE_ARGS:-}" ]; then
  TEMPLATE_ARGS=(--chat-template-args "$MLX_CHAT_TEMPLATE_ARGS")
fi

# Abort only if OUR mlx_lm server is already answering here (avoid a duplicate). A bare lsof
# check false-positives on unrelated listeners sharing the port (e.g. a Docker container on
# 0.0.0.0:PORT), which would crash-loop under launchd. Exit 0 (not 1) so "already running" isn't
# treated as a crash.
if curl -s --max-time 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | grep -q '"data"'; then
  echo "An mlx_lm server is already responding on $HOST:$PORT — not starting a duplicate."
  exit 0
fi

echo "Starting Reviewer on $HOST:$PORT (model: $MODEL)"
echo "Log: $HOME/ai/logs/reviewer.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --max-tokens "$MAX_TOKENS" \
  ${TEMPLATE_ARGS[@]+"${TEMPLATE_ARGS[@]}"} \
  --prompt-cache-size "$PROMPT_CACHE_SIZE" \
  --prompt-cache-bytes "$PROMPT_CACHE_BYTES" \
  ${DRAFT_ARGS[@]+"${DRAFT_ARGS[@]}"} \
  >> "$HOME/ai/logs/reviewer.log" 2>&1
