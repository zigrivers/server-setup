#!/usr/bin/env bash
set -euo pipefail

# Quick chat smoke test against all three local endpoints. Prints the
# model output and exit status for each so it's obvious which one is
# misconfigured.

ORCH_MODEL="${ORCH_MODEL:-$HOME/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16}"
DEV_MODEL="${DEV_MODEL:-$HOME/ai/models/developer-qwen36-27b-heretic2-mixed94}"
REVIEW_MODEL="${REVIEW_MODEL:-$HOME/ai/models/reviewer-qwen36-27b-heretic-bf16}"

build_payload() {
  local model="$1"
  local user_msg="$2"
  MODEL_FOR_PY="$model" USER_FOR_PY="$user_msg" python3 -c '
import json, os
print(json.dumps({
    "model": os.environ["MODEL_FOR_PY"],
    "messages": [
        {"role": "system", "content": "Answer directly and briefly. Do not show reasoning."},
        {"role": "user", "content": os.environ["USER_FOR_PY"]},
    ],
    "max_tokens": 256,
    "temperature": 0.1,
}))'
}

call_model() {
  local name="$1"
  local url="$2"
  local model="$3"
  echo "=== $name ==="
  local payload
  payload="$(build_payload "$model" "Say exactly: $name OK")"
  curl -s "$url/chat/completions" \
    -H "Content-Type: application/json" \
    --data-binary "$payload"
  echo
  echo
}

call_model "orchestrator" "http://127.0.0.1:8001/v1" "$ORCH_MODEL"
call_model "developer"    "http://10.10.10.2:8002/v1" "$DEV_MODEL"
call_model "reviewer"     "http://10.10.10.2:8003/v1" "$REVIEW_MODEL"
