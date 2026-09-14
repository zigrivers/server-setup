#!/usr/bin/env bash
# Reproduce the mlx-lm Metal buffer-descriptor leak with one long completion.
#
# mlx-lm leaks one live Metal buffer per SSM layer per generated token on the qwen3_5 hybrids
# (ml-explore/mlx-lm#1845); Metal caps live buffers at mx.device_info()["resource_limit"]
# (499000 here), so a single completion longer than ~499000/(ssm_layers-1) tokens kills the
# server's generation thread with:
#   RuntimeError: [metal::malloc] Resource limit (499000) exceeded.
#
# Usage:  repro-metal-leak.sh BASE_URL MODEL_ID [MAX_TOKENS] [SERVER_LOG]
#   BASE_URL   e.g. http://127.0.0.1:8009/v1  (use a SPARE server — this kills its decode thread)
#   MODEL_ID   the exact path/id the server was started with (model ids are load instructions)
#   MAX_TOKENS completion budget, default 16000 (27B crashes near 10.6k on 0.31.3)
#   SERVER_LOG if given, the script watches it and aborts the request when the traceback appears
# Exit 0 = completion finished (leak not hit), exit 2 = server crashed / request failed.
set -euo pipefail

BASE_URL="${1:?BASE_URL}"
MODEL="${2:?MODEL_ID}"
MAX_TOKENS="${3:-16000}"
SERVER_LOG="${4:-}"

export MODEL MAX_TOKENS
PAYLOAD="$(python3 -c '
import json, os
print(json.dumps({
  "model": os.environ["MODEL"],
  "messages": [{"role": "user", "content":
    "Write the integers from 1 to 6000, one per line, with no commentary before or after."}],
  "max_tokens": int(os.environ["MAX_TOKENS"]),
  "temperature": 0,
  "chat_template_kwargs": {"enable_thinking": False},
}))')"

START="$(date +%s)"
# When the generation thread dies the HTTP thread never answers, so the request would hang until
# --max-time. If we have the server log, watch it and abort the request on first sight of the crash.
BODY_FILE="$(mktemp)"; trap 'rm -f "$BODY_FILE"' EXIT
curl -s --max-time 3600 "$BASE_URL/chat/completions" -H 'Content-Type: application/json' -d "$PAYLOAD" -o "$BODY_FILE" &
CURL_PID=$!
if [ -n "$SERVER_LOG" ]; then
  ( while kill -0 "$CURL_PID" 2>/dev/null; do
      grep -q "Resource limit (499000) exceeded" "$SERVER_LOG" && { kill "$CURL_PID" 2>/dev/null; break; }
      sleep 5
    done ) &
fi
wait "$CURL_PID" || true
ELAPSED=$(( $(date +%s) - START ))

python3 - "$BODY_FILE" "$ELAPSED" <<'PY'
import json, sys
body, elapsed = open(sys.argv[1]).read(), int(sys.argv[2])
try:
    d = json.loads(body)
except Exception:
    print(f"REQUEST FAILED after {elapsed}s (no JSON): {body[:200]!r}")
    sys.exit(2)
u = d.get("usage") or {}
ct = u.get("completion_tokens", 0)
fin = (d.get("choices") or [{}])[0].get("finish_reason")
print(f"completion_tokens={ct} finish_reason={fin} elapsed={elapsed}s tok/s={ct/max(elapsed,1):.1f}")
if d.get("error"):
    print("error:", d["error"]); sys.exit(2)
PY
