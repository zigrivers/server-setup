#!/usr/bin/env bash
# Serve one role (orchestrator | developer | reviewer) with oMLX. Called by scripts/start-<role>.sh.
#
# Why oMLX and not mlx_lm.server: measured 2026-10-21 on the same Qwen3.6-35B-A3B weights on M1,
# mlx_lm.server behind the #1845 leak shim decoded at 19 tok/s, stock mlx_lm.server at 44, and oMLX
# at 90 (plus 2x prompt processing and a prompt cache that survives across requests). oMLX also
# runs the models' native multi-token-prediction heads (the *-mtp builds), which doubled the dense
# 27B developer from 20 to 47 tok/s. Rollback: LOCAL_AI_SERVER=mlx_lm in the role launcher.
#
# Required env (set by the role launcher): ROLE, PORT, HOST, MODEL (absolute path of the weights).
# Optional: OMLX_VENV (default ~/ai/omlx/.venv), OMLX_MAX_CONCURRENT (default 8),
#           OMLX_SSD_CACHE_MAX (default 100GB), OMLX_MODEL_MAX_TOKENS (default 8192).
set -euo pipefail

: "${ROLE:?ROLE is required}" "${PORT:?PORT is required}" "${HOST:?HOST is required}" "${MODEL:?MODEL is required}"
OMLX_VENV="${OMLX_VENV:-$HOME/ai/omlx/.venv}"
OMLX_BIN="$OMLX_VENV/bin/omlx"
KEY_FILE="${OMLX_KEY_FILE:-$HOME/ai/omlx/omlx.key}"
MODEL_DIR="$HOME/ai/omlx-models/$ROLE"
LOG="$HOME/ai/logs/$ROLE.log"
MODEL_ID="$(basename "$MODEL")"
mkdir -p "$HOME/ai/logs" "$MODEL_DIR"

[ -x "$OMLX_BIN" ] || { echo "oMLX not installed at $OMLX_BIN (see docs/OMLX.md)"; exit 1; }
[ -f "$MODEL/config.json" ] || { echo "Model not found: $MODEL"; exit 1; }

# oMLX serves every model under --model-dir. Each role gets its own directory holding exactly one
# symlink, so a role can never pick up (and load) a neighbour's weights.
find "$MODEL_DIR" -maxdepth 1 -type l -delete
ln -s "$MODEL" "$MODEL_DIR/$MODEL_ID"

# A key is mandatory on a non-loopback bind. Inference stays keyless for the stack's clients via the
# persisted allow_unauthenticated_inference setting (set below); the key only guards the admin API.
if [ ! -s "$KEY_FILE" ]; then (umask 077; openssl rand -hex 24 > "$KEY_FILE"); fi
KEY="$(cat "$KEY_FILE")"

# Abort only if OUR server is already answering here (duplicate under launchd). Exit 0 on purpose.
if curl -s --max-time 3 "http://$HOST:$PORT/v1/models" 2>/dev/null | grep -q '"data"'; then
  echo "A model server is already responding on $HOST:$PORT — not starting a duplicate."
  exit 0
fi

echo "Starting $ROLE with oMLX: model=$MODEL_ID url=http://$HOST:$PORT/v1 log=$LOG"

# Apply persistent settings once the server is up (idempotent; runs in the background so the
# server process itself is what launchd supervises).
(
  for _ in $(seq 1 120); do
    curl -s --max-time 2 "http://$HOST:$PORT/v1/models" -H "Authorization: Bearer $KEY" 2>/dev/null | grep -q '"data"' && break
    sleep 2
  done
  AUTH=(-H "Authorization: Bearer $KEY" -H "Content-Type: application/json")
  curl -s -X POST "${AUTH[@]}" -d '{"allow_unauthenticated_inference": true}' \
    "http://$HOST:$PORT/admin/api/global-settings" >/dev/null 2>&1 || true
  # Pinned = never evicted; max_tokens is the cap for clients that send none (mlx_lm had 8192).
  curl -s -X PUT "${AUTH[@]}" -d "{\"is_pinned\": true, \"max_tokens\": ${OMLX_MODEL_MAX_TOKENS:-8192}}" \
    "http://$HOST:$PORT/admin/api/models/$MODEL_ID/settings" >/dev/null 2>&1 || true
  # Load now rather than on the first request, so the first caller does not wait for the weights.
  curl -s -X POST "${AUTH[@]}" "http://$HOST:$PORT/admin/api/models/$MODEL_ID/load" >/dev/null 2>&1 || true
) &

exec "$OMLX_BIN" serve \
  --model-dir "$MODEL_DIR" \
  --host "$HOST" \
  --port "$PORT" \
  --api-key "$KEY" \
  --headless \
  --no-hf-cache \
  --max-concurrent-requests "${OMLX_MAX_CONCURRENT:-8}" \
  --paged-ssd-cache-max-size "${OMLX_SSD_CACHE_MAX:-100GB}" \
  --log-level info \
  >> "$LOG" 2>&1
