#!/usr/bin/env bash
# Transparent PATH shim that counts an agent-CLI invocation in the dashboard, then runs the REAL
# binary. Installed in ~/.local/cli-shims/ as codex / grok / agy (symlinks to this script), with that
# dir placed EARLY on PATH. It must never recurse into itself and never break the real tool.
#
# How it stays safe:
#   - resolves the real binary by removing the shim dir from PATH (so `command -v` finds the real one)
#   - if it can't find a real binary distinct from itself, it fails loudly (never silently swallows)
#   - the usage ping is best-effort + time-boxed, so a down meter can't affect the CLI
set -uo pipefail

tool="$(basename "$0")"
case "$tool" in
  agy)          label="antigravity" ;;  # Google Antigravity CLI is invoked as `agy`
  cursor-agent) label="cursor" ;;       # Cursor's headless agent CLI
  *)            label="$tool" ;;         # codex, grok
esac

shim_dir="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
# PATH with the shim dir stripped out, so `command -v` resolves to the real binary, not this shim.
clean_path="$(printf %s ":$PATH:" | sed "s#:${shim_dir}:#:#g" | sed 's/^://; s/:$//')"
real="$(PATH="$clean_path" command -v "$tool" 2>/dev/null || true)"

# Best-effort usage ping (never blocks/fails the CLI).
INGEST="${DASHBOARD_INGEST:-http://127.0.0.1:9100}"
curl -s -m 2 -X POST "$INGEST/usage" -H 'content-type: application/json' \
  --data "{\"client\":\"$label\"}" >/dev/null 2>&1 || true

if [ -n "$real" ] && [ "$real" != "$0" ]; then
  exec "$real" "$@"
fi
echo "cli-track-shim: real '$tool' not found on PATH (shim dir excluded) — not running" >&2
exit 127
