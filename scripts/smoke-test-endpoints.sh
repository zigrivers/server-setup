#!/usr/bin/env bash
set -euo pipefail

# Quick chat smoke test against all three local endpoints. Prints the
# model output and exit status for each so it's obvious which one is
# misconfigured.

# Source .env for model paths (dev/reviewer live on Machine 2 under /Users/admin)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

# Ask each endpoint which model it is serving instead of hardcoding a path. This is not tidiness:
# mlx_lm.server LOADS whatever model id it is sent, so a stale path here does not fail the smoke
# test — it silently pulls a SECOND copy of old weights into memory (a 65 GB surprise on M1) and
# reports "OK" from the wrong model. The served model is the id that is a filesystem path; the
# other ids in /v1/models are whatever else sits in the HF cache.
served_model() {
  curl -s --max-time 5 "$1/models" | python3 -c '
import json, sys
try:
    ids = [d["id"] for d in json.load(sys.stdin).get("data", [])]
except Exception:
    sys.exit(1)
print(next((i for i in ids if i.startswith("/")), ids[0] if ids else ""))'
}

ORCH_MODEL="${ORCH_MODEL:-$(served_model http://127.0.0.1:8001/v1)}"
DEV_MODEL="${DEV_MODEL:-$(served_model http://10.10.10.2:8002/v1)}"
REVIEW_MODEL="${REVIEW_MODEL:-$(served_model http://10.10.10.2:8003/v1)}"

for pair in "orchestrator:$ORCH_MODEL" "developer:$DEV_MODEL" "reviewer:$REVIEW_MODEL"; do
  if [[ -z "${pair#*:}" ]]; then
    echo "Could not read a served model from the ${pair%%:*} endpoint — is it up?" >&2
    exit 1
  fi
done

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
