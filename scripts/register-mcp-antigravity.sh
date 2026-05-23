#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$REPO_DIR" << 'EOF'
import json
import os
import sys

repo_dir = sys.argv[1]
home_dir = os.path.expanduser("~")
config_path = os.path.expanduser('~/.gemini/antigravity-cli/mcp_config.json')

os.makedirs(os.path.dirname(config_path), exist_ok=True)

if os.path.exists(config_path):
    try:
        with open(config_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Warning: could not parse existing mcp_config.json: {e}. Reinitializing.")
        data = {}
else:
    data = {}

if not isinstance(data, dict):
    data = {}

if 'mcpServers' not in data:
    data['mcpServers'] = {}

allowed_roots = f"{home_dir}/ai/workspaces:{home_dir}/code:{home_dir}/Developer:{home_dir}/projects:{repo_dir}"
default_workspace = f"{home_dir}/ai/workspaces"
local_exec_plan_bin = f"{repo_dir}/.venv/bin/local-exec-plan"
python_bin = f"{repo_dir}/.venv/bin/python"
server_py = f"{repo_dir}/mcp/local_delegate_mcp/server.py"

data['mcpServers']['local-ai-delegate'] = {
    "command": python_bin,
    "args": [server_py],
    "env": {
        "LOCAL_AI_ALLOWED_ROOTS": allowed_roots,
        "LOCAL_AI_DEFAULT_WORKSPACE": default_workspace,
        "LOCAL_EXEC_PLAN_BIN": local_exec_plan_bin,
        "ORCH_BASE_URL": "http://127.0.0.1:8001/v1",
        "DEV_BASE_URL": "http://10.10.10.2:8002/v1",
        "REVIEW_BASE_URL": "http://10.10.10.2:8003/v1"
    }
}

with open(config_path, 'w') as f:
    json.dump(data, f, indent=2)

print(f"Registered local-ai-delegate MCP server in {config_path}")
EOF
