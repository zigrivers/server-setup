#!/usr/bin/env bash
set -euo pipefail

echo "=== Machine 1 AI status ==="
date

echo
echo "=== Orchestrator port ==="
lsof -nP -iTCP:8001 -sTCP:LISTEN || echo "Nothing listening on 8001"

echo
echo "=== Orchestrator API ==="
curl -s http://127.0.0.1:8001/v1/models || echo "Orchestrator API unavailable"

echo
echo
echo "=== Machine 2 Developer API ==="
curl -s http://10.10.10.2:8002/v1/models || echo "Developer API unavailable"

echo
echo
echo "=== Machine 2 Reviewer API ==="
curl -s http://10.10.10.2:8003/v1/models || echo "Reviewer API unavailable"

echo
echo
echo "=== Machine 2 MTP / Security API (optional, 8004) ==="
curl -s --max-time 2 http://10.10.10.2:8004/v1/models || echo "MTP API unavailable (this is expected unless the experimental lane is running)"

echo
echo
echo "=== Memory pressure ==="
memory_pressure | tail -20 || true
