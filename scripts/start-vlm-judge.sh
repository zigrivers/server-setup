#!/usr/bin/env bash
set -euo pipefail

# VLM judge server (Machine 2). Serves the 2d-3d-pipeline's concept/mesh judge
# model (Qwen3-VL) over mlx_vlm's OpenAI-compatible HTTP server, so judge calls
# from Machine 1 need no in-process model load and no vlm-env on the caller.
# Metered lane: 127.0.0.1:9008 on Machine 1 -> here (see local-ai-dashboard).
#
# Unlike the mlx_lm workers this uses its own venv (~/ai/venvs/vlm): mlx-vlm
# and mlx-lm move at different release cadences and pin different mlx versions.

mkdir -p "$HOME/ai/logs"

if [ -f "$HOME/ai/local-ai-stack/.env" ]; then
  set -a; . "$HOME/ai/local-ai-stack/.env"; set +a
fi

HOST="${WORKER_HOST:-10.10.10.2}"
PORT="${VLM_PORT:-8006}"
VLM_VENV="${VLM_VENV:-$HOME/ai/venvs/vlm}"
# HF repo id, matching the 2d-3d-pipeline judge default (gate G2 picked the
# 30B-A3B tier; the 8B tier does not discriminate 3/4-view compliance).
MODEL="${VLM_MODEL:-mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit}"

if [ ! -x "$VLM_VENV/bin/python" ]; then
  echo "vlm venv not found at $VLM_VENV — create it with:" >&2
  echo "  uv venv $VLM_VENV --python 3.12 && uv pip install --python $VLM_VENV/bin/python 'mlx-vlm==0.6.12'" >&2
  exit 1
fi

# Abort only if OUR server is already answering here (avoid a duplicate). Same
# rationale as start-developer.sh: a bare lsof check false-positives on
# unrelated listeners, which would crash-loop under launchd. Exit 0 so
# "already running" isn't treated as a crash.
if curl -s --max-time 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | grep -q '"data"'; then
  echo "A VLM server is already responding on $HOST:$PORT — not starting a duplicate."
  exit 0
fi

echo "Starting VLM judge on $HOST:$PORT (model: $MODEL)"
echo "Log: $HOME/ai/logs/vlm-judge.log"
exec "$VLM_VENV/bin/python" -m mlx_vlm server \
  --host "$HOST" \
  --port "$PORT" \
  --model "$MODEL" \
  >> "$HOME/ai/logs/vlm-judge.log" 2>&1
