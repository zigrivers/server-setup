#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Usage: $0 BASE_URL MODEL PROMPT_FILE"
  echo "Example: $0 http://127.0.0.1:8001/v1 /Users/admin/ai/models/orch-bf16 benchmarks/prompts/01_architecture_plan.md"
  exit 1
fi

BASE_URL="$1"
MODEL="$2"
PROMPT_FILE="$3"
PROMPT="$(cat "$PROMPT_FILE")"

START="$(date +%s)"

curl -s "$BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\n    \"model\": \"$MODEL\",\n    \"messages\": [\n      {\"role\": \"system\", \"content\": \"Answer directly. Be precise. Do not include hidden reasoning traces.\"},\n      {\"role\": \"user\", \"content\": $(python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' <<< "$PROMPT")}\n    ],\n    \"max_tokens\": 4096,\n    \"temperature\": 0.3\n  }"

END="$(date +%s)"
echo
echo "Elapsed seconds: $((END - START))"
