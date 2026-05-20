#!/usr/bin/env bash
set -euo pipefail

ORCH_MODEL="${ORCH_MODEL:-$HOME/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16}"
DEV_MODEL="${DEV_MODEL:-/Users/admin/ai/models/developer-qwen36-27b-heretic2-mixed94}"
REVIEW_MODEL="${REVIEW_MODEL:-/Users/admin/ai/models/reviewer-qwen36-27b-heretic-bf16}"

call_model() {
  local name="$1"
  local url="$2"
  local model="$3"
  echo "=== $name ==="
  curl -s "$url/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{\n      \"model\": \"$model\",\n      \"messages\": [\n        {\"role\": \"system\", \"content\": \"Answer directly and briefly. Do not show reasoning.\"},\n        {\"role\": \"user\", \"content\": \"Say exactly: $name OK\"}\n      ],\n      \"max_tokens\": 256,\n      \"temperature\": 0.1\n    }"
  echo
  echo
}

call_model "orchestrator" "http://127.0.0.1:8001/v1" "$ORCH_MODEL"
call_model "developer" "http://10.10.10.2:8002/v1" "$DEV_MODEL"
call_model "reviewer" "http://10.10.10.2:8003/v1" "$REVIEW_MODEL"
