#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Usage: $0 BASE_URL MODEL PROMPT_FILE"
  echo "Example: $0 http://127.0.0.1:8001/v1 \$HOME/ai/models/orch-bf16 benchmarks/prompts/01_architecture_plan.md"
  exit 1
fi

BASE_URL="$1"
MODEL="$2"
PROMPT_FILE="$3"

if [ ! -f "$PROMPT_FILE" ]; then
  echo "Prompt file not found: $PROMPT_FILE" >&2
  exit 1
fi

START="$(date +%s)"

# Build the JSON payload via Python so the prompt is properly escaped
# (handles newlines, quotes, and backslashes correctly).
export MODEL PROMPT_FILE
PAYLOAD="$(python3 -c '
import json, os
payload = {
    "model": os.environ["MODEL"],
    "messages": [
        {"role": "system", "content": "Answer directly. Be precise. Do not include hidden reasoning traces."},
        {"role": "user", "content": open(os.environ["PROMPT_FILE"]).read()},
    ],
    "max_tokens": 4096,
    "temperature": 0.3,
}
print(json.dumps(payload))
')"

curl -s "$BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  --data-binary "$PAYLOAD"

END="$(date +%s)"
echo
echo "Elapsed seconds: $((END - START))"
