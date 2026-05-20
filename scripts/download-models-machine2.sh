#!/usr/bin/env bash
set -euo pipefail

# Run on Machine 2. Requires `hf auth login` first.
mkdir -p "$HOME/ai/models"
cd "$HOME/ai"

hf download \
  TheCluster/Qwen3.6-27B-Heretic2-Uncensored-Finetune-Thinking-MLX-mixed-9.4bit \
  --local-dir "$HOME/ai/models/developer-qwen36-27b-heretic2-mixed94"

hf download \
  TheCluster/Qwen3.6-27B-Heretic-MLX-bf16 \
  --local-dir "$HOME/ai/models/reviewer-qwen36-27b-heretic-bf16"
