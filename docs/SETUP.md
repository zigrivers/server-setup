# Setup

## 1. Put this repo in place

```bash
mkdir -p ~/ai
mv local-ai-stack-repo ~/ai/local-ai-stack
cd ~/ai/local-ai-stack
```

## 2. Initialize git

```bash
git init
git add .
git commit -m "Initial local AI stack repo"
```

## 3. Create Machine 1 repo venv

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[all]'
```

If you only want the controller and MCP tools on Machine 1:

```bash
uv pip install -e '.[mcp]'
```

If this repo also needs to run MLX servers on the machine:

```bash
uv pip install -e '.[mlx,mcp]'
```

## 4. Create `.env`

```bash
cp configs/env.machine1.example .env
```

Edit `.env` and confirm:

```text
ORCH_BASE_URL=http://127.0.0.1:8001/v1
DEV_BASE_URL=http://10.10.10.2:8002/v1
REVIEW_BASE_URL=http://10.10.10.2:8003/v1
```

Confirm model paths match the machine hosting each server.

## 5. Download Machine 1 Orchestrator model

```bash
hf auth login
scripts/download-models-machine1.sh
```

## 6. Start Machine 1 Orchestrator

```bash
scripts/start-orchestrator.sh
scripts/m1-ai-status.sh
```

## 7. Set up Machine 2

Copy or clone this repo onto Machine 2 too, preferably also at:

```text
~/ai/local-ai-stack
```

Then run:

```bash
cd ~/ai/local-ai-stack
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[mlx]'
hf auth login
scripts/download-models-machine2.sh
scripts/start-worker-models.sh
scripts/m2-ai-status.sh
```

## 8. Smoke test from Machine 1

```bash
cd ~/ai/local-ai-stack
source .venv/bin/activate

python -m local_ai_stack.local_agents \
  --workspace ~/ai/workspaces/hello_agent \
  "Create a tiny README.md file that says the split-machine local multi-agent system is working."
```

## 9. Install Claude skills

```bash
scripts/install-claude-skills.sh
```

Restart Claude Code and run:

```text
/skills
```

## 10. Register MCP bridge

For Claude Code:

```bash
scripts/register-mcp-claude.sh
```

For Codex:

```bash
scripts/register-mcp-codex.sh
```

Then edit `~/.codex/config.toml` and add/increase:

```toml
startup_timeout_sec = 20
tool_timeout_sec = 3600
```
