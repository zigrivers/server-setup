#!/usr/bin/env bash
set -euo pipefail

echo "=== Machine 2 AI status ==="
date

echo
echo "=== Listening ports ==="
lsof -nP -iTCP:8002 -iTCP:8003 -iTCP:8004 -sTCP:LISTEN || true

echo
echo "=== Developer API ==="
curl -s http://10.10.10.2:8002/v1/models || echo "Developer API unavailable"

echo
echo
echo "=== Reviewer API ==="
curl -s http://10.10.10.2:8003/v1/models || echo "Reviewer API unavailable"

echo
echo
echo "=== Memory pressure ==="
memory_pressure | tail -20 || true

echo
echo "=== Recent logs ==="
for f in "$HOME"/ai/logs/developer.log "$HOME"/ai/logs/reviewer.log; do
  [ -e "$f" ] || continue
  echo "--- $f ---"
  tail -20 "$f"
done
