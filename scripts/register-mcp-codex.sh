#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

codex mcp add local-ai-delegate \
  --env LOCAL_AI_ALLOWED_ROOTS="$HOME/ai/workspaces:$HOME/code:$HOME/Developer:$HOME/projects:$REPO_DIR" \
  --env LOCAL_AI_DEFAULT_WORKSPACE="$HOME/ai/workspaces" \
  --env LOCAL_EXEC_PLAN_BIN="$REPO_DIR/.venv/bin/local-exec-plan" \
  --env ORCH_BASE_URL="http://127.0.0.1:8001/v1" \
  --env DEV_BASE_URL="http://10.10.10.2:8002/v1" \
  --env REVIEW_BASE_URL="http://10.10.10.2:8003/v1" \
  -- "$REPO_DIR/.venv/bin/python" "$REPO_DIR/mcp/local_delegate_mcp/server.py"

echo "Now edit ~/.codex/config.toml and ensure this MCP block has:"
echo "startup_timeout_sec = 20"
echo "tool_timeout_sec = 3600"
