#!/usr/bin/env bash
set -euo pipefail

# Run on Machine 1. Requires `hf auth login` first.
mkdir -p "$HOME/ai/models"
cd "$HOME/ai"

hf download \
  TheCluster/Qwen3.6-35B-A3B-Heretic-MLX-bf16 \
  --local-dir "$HOME/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16"

# Optional fallback.
hf download \
  TheCluster/Qwen3.6-35B-A3B-Heretic-MLX-mixed-9bit \
  --local-dir "$HOME/ai/models/orchestrator-qwen36-35b-a3b-heretic-mixed9"
