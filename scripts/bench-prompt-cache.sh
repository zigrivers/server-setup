#!/usr/bin/env bash
set -euo pipefail

# Prove the mlx_lm prompt/prefix KV cache works: send a BYTE-IDENTICAL long prompt twice and
# compare time-to-first-token (TTFT). The 2nd call should hit the prefix cache and start faster.
# Then fire a few distinct long prefixes + re-send the first to confirm the server stays up under
# the byte cap. Usage: bench-prompt-cache.sh [baseUrl]   (default http://127.0.0.1:8001/v1)

BASE="${1:-http://127.0.0.1:8001/v1}"
MODEL="$(curl -s --max-time 10 "$BASE/models" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"][0]["id"])')"
[ -n "$MODEL" ] || { echo "could not resolve model id from $BASE/models"; exit 1; }

# Build a ~1.5k-token shared prefix (byte-identical every call → guaranteed prefix match).
PREFIX="$(python3 -c 'print(("You are a meticulous assistant. Context: " + ("the quick brown fox jumps over the lazy dog. " * 220)).strip())')"

# Measure TTFT for one streamed completion. Prints seconds-to-first-token.
ttft() {
  local prompt="$1"
  python3 - "$BASE" "$MODEL" "$prompt" <<'PY'
import sys, json, time, urllib.request
base, model, prompt = sys.argv[1], sys.argv[2], sys.argv[3]
body = json.dumps({"model": model, "stream": True, "max_tokens": 8,
                   "messages": [{"role": "user", "content": prompt + "\n\nReply with: ok"}]}).encode()
req = urllib.request.Request(base + "/chat/completions", data=body,
                             headers={"content-type": "application/json"}, method="POST")
t0 = time.time()
with urllib.request.urlopen(req, timeout=180) as r:
    for line in r:
        if line.strip().startswith(b"data:") and b"[DONE]" not in line:
            print(f"{time.time()-t0:.2f}"); break
PY
}

echo "Endpoint: $BASE   model: $(basename "$MODEL")"
echo "Cold (first call, no cache)…"
COLD="$(ttft "$PREFIX")"
echo "  cold TTFT: ${COLD}s"
echo "Warm (same prefix, should hit cache)…"
WARM="$(ttft "$PREFIX")"
echo "  warm TTFT: ${WARM}s"

python3 -c "
cold, warm = float('$COLD'), float('$WARM')
if warm < cold:
    print(f'  -> prefix cache HIT: {cold/warm:.1f}x faster TTFT ({cold:.2f}s -> {warm:.2f}s)')
else:
    print('  -> no speedup; check the server log for a \"Prompt Cache:\" line and confirm the prefix matched byte-for-byte')
"

echo "Stability under the byte cap (3 distinct prefixes + re-send first)…"
for i in 1 2 3; do
  P="$(python3 -c "print('Distinct prefix $i: ' + ('lorem ipsum dolor sit amet. ' * 200))")"
  ttft "$P" >/dev/null && echo "  distinct $i: ok"
done
ttft "$PREFIX" >/dev/null && echo "  re-send first: ok (server healthy under cap)"
