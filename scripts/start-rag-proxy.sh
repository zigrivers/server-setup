#!/usr/bin/env bash
set -euo pipefail

# Launch the RAG proxy (Machine 1, loopback). Mirrors start-orchestrator.sh's hardened preflight:
# abort (exit 0, not 1) only if OUR proxy is already answering on /healthz, so launchd never treats
# "already running" as a crash. Binds 127.0.0.1 (+ RAG_PROXY_BRIDGE_HOST if set).

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
source "$REPO_DIR/.venv/bin/activate"
mkdir -p "$HOME/ai/logs"

HOST="${RAG_PROXY_HOST:-127.0.0.1}"
PORT="${RAG_PROXY_PORT:-9200}"
export UPSTREAM_BASE_URL="${UPSTREAM_BASE_URL:-http://127.0.0.1:9002}"

# Abort only if OUR proxy already answers here (distinguish by the /healthz service marker, not a bare
# lsof which false-positives on unrelated listeners). Exit 0 so launchd doesn't see a crash.
if curl -s --max-time 3 "http://$HOST:$PORT/healthz" 2>/dev/null | grep -q '"service":"rag-proxy"'; then
  echo "rag-proxy already responding on $HOST:$PORT — not starting a duplicate."
  exit 0
fi

echo "Starting RAG proxy:"
echo "  URL:      http://$HOST:$PORT  (/v1/* -> $UPSTREAM_BASE_URL)"
echo "  Log:      $HOME/ai/logs/rag-proxy.log"

# Canonical script path (scripts are symlinked into the stack repo; single source of truth).
exec python "$REPO_DIR/scripts/rag-proxy.py" >> "$HOME/ai/logs/rag-proxy.log" 2>&1
