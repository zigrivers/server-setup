#!/usr/bin/env bash
set -euo pipefail

# Bulk-classification lane: the Orchestrator's weights served WITHOUT thinking, plus an MTP drafter.
# On-demand, not a LaunchAgent — it pins ~38 GB resident and is only wanted while a batch job runs.
#
# Why this exists. Bulk classification wants throughput, not reasoning. The Orchestrator on :9001
# does this job correctly *provided* the caller sends chat_template_kwargs enable_thinking=False —
# mlx-lm honours that flag (median 1.17s per enrichment item, valid JSON every time). Without it,
# the same endpoint reasons past 1,500 tokens and never answers at all.
#
# This lane serves the same weights on mlx-vlm, which has no thinking template to apply, plus an
# MTP drafter for speculative decoding. Measured 2026-08-24 on the Phase 8 enrichment prompt:
#
#   :9001 mlx-lm, enable_thinking=False   median 1.17s   valid JSON 4/4
#   this lane, MTP drafter                median 0.72s   valid JSON 4/4     (~1.6x)
#
# So this is a speed option for six-figure batches, not a fix for anything. At ~2,600 items/hour it
# turns a 58-hour run into roughly 36. For a few hundred items, just use :9001 — it is already
# running, already metered, and needs no hand-started process.
#
# Runtime is mlx-vlm from an ISOLATED venv (~/ai/mtp-venv). Production keeps serving from
# ~/ai/local-ai-stack/.venv on mlx-lm 0.31.3, untouched — upgrading one must never risk the other.
# Do NOT point review or coding traffic here: mlx-vlm cannot enable thinking, measured at 89% -> 78%
# recall on the code-review eval. Non-thinking is right for classification and wrong for review.

VENV="${ENRICH_VENV:-$HOME/ai/mtp-venv}"
MODEL="${ENRICH_MODEL_PATH:-$HOME/ai/models/orchestrator-qwen36-35b-a3b-heretic-mixed9}"
DRAFTER="${ENRICH_DRAFT_PATH:-$HOME/ai/models/qwen36-35b-a3b-mtp-drafter}"
HOST="${ENRICH_HOST:-127.0.0.1}"
PORT="${ENRICH_PORT:-8010}"
LOG="$HOME/ai/logs/enrich-lane.log"
mkdir -p "$HOME/ai/logs"

if [ ! -x "$VENV/bin/python3" ]; then
  echo "Missing venv $VENV. Create it once:" >&2
  echo "  $HOME/ai/local-ai-stack/.venv/bin/python3 -m venv $VENV" >&2
  echo "  $VENV/bin/pip install 'mlx-vlm==0.6.15' jinja2" >&2
  exit 1
fi

if curl -s --max-time 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | grep -q '"data"'; then
  echo "Enrichment lane already answering on $HOST:$PORT — not starting a duplicate."
  exit 0
fi

echo "Starting enrichment lane:"
echo "  Model:   $MODEL"
echo "  Drafter: $DRAFTER (MTP speculative decoding)"
echo "  URL:     http://$HOST:$PORT/v1"
echo "  Log:     $LOG"
nohup "$VENV/bin/python3" -m mlx_vlm server \
  --model "$MODEL" \
  --draft-model "$DRAFTER" \
  --draft-kind mtp \
  --draft-block-size 4 \
  --host "$HOST" \
  --port "$PORT" >> "$LOG" 2>&1 &

for _ in $(seq 1 120); do
  if curl -s --max-time 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | grep -q '"data"'; then
    echo "Ready. Stop it when the batch finishes:  pkill -f 'mlx_vlm server.*--port $PORT'"
    exit 0
  fi
  sleep 5
done
echo "Lane did not come up within 10 minutes — see $LOG" >&2
exit 1
