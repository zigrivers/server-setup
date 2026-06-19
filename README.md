# Local AI Stack Repo

This repository is the source-controlled home for your two-Mac local AI development system.

It is designed to be edited and improved with **Claude Code** and **Codex**, while the actual local execution pipeline runs on your Apple Silicon machines:

```text
Machine 1 / daily driver / control plane
  - Claude Code + Codex
  - VS Code / Cursor
  - LangGraph controller
  - MCP bridge
  - local Orchestrator model on 127.0.0.1:8001

Thunderbolt Bridge
  - Machine 1: 10.10.10.1
  - Machine 2: 10.10.10.2

Machine 2 / inference worker
  - Developer model on 10.10.10.2:8002
  - Reviewer model on 10.10.10.2:8003
  - optional experimental MTP / security reviewer on 10.10.10.2:8004
```

## What this repo contains

```text
src/local_ai_stack/
  local_agents.py          LangGraph Orchestrator → Developer → Reviewer loop
  local_exec_plan.py       Executes frontier-generated plan files in git worktrees

mcp/local_delegate_mcp/
  server.py                MCP bridge for Claude Code / Codex

scripts/
  launchers, installers, download helpers, status checks, benchmark helpers

.agents/skills/
  delegate-local/          Antigravity CLI skill for plan → local execution
  local-review/            Antigravity CLI skill for local second-opinion review
  local-ai-status/         Antigravity CLI skill for checking endpoints

skills/claude/
  delegate-local/          Claude Code skill for plan → local execution
  local-review/            Claude Code skill for local second-opinion review
  local-ai-status/         Claude Code skill for checking endpoints

configs/
  env examples, endpoint examples, launchd templates

docs/
  architecture, setup, operations, troubleshooting, and workflow docs
  rag.md / rag-proxy.md    local RAG toolkit + the transparent per-project RAG proxy (:9200)
  observability.md         every model in one dashboard (metered + reported paths)
  dev-stack-models.md      drive local + GLM-5.2 + DeepSeek from OpenCode and MMR

prompts/
  reusable prompts for frontier planning and review

plans/
  starter example plan files

benchmarks/
  local model benchmark prompts
```

## Quick start

Unzip this repo and put it somewhere stable, preferably:

```bash
mkdir -p ~/ai
mv local-ai-stack-repo ~/ai/local-ai-stack
cd ~/ai/local-ai-stack
```

Initialize git:

```bash
git init
git add .
git commit -m "Initial local AI stack repo"
```

Create the repo virtual environment on **Machine 1**:

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[mcp]'
```

Copy the environment template:

```bash
cp configs/env.machine1.example .env
```

Edit `.env` and confirm the model paths match your actual machines.

Start the Orchestrator on Machine 1:

```bash
scripts/start-orchestrator.sh
scripts/m1-ai-status.sh
```

Make sure the Machine 2 worker models are already running, then smoke test:

```bash
python -m local_ai_stack.local_agents \
  --workspace ~/ai/workspaces/hello_agent \
  "Create a tiny README.md file that says the split-machine local multi-agent system is working."
```

## Recommended iteration workflow

Use this repo itself the same way you want to use future project repos:

1. Ask Claude Code or Codex to create a plan in `plans/`.
2. Review the plan yourself.
3. Let the local stack execute the plan in a worktree.
4. Ask Claude/Codex to do final architecture and docs review.
5. Merge manually.

The principle is simple:

```text
Frontier models write the contract.
Local models execute the contract.
You approve the merge.
```

## Important safety defaults

- Local agents should only work inside git repos or isolated worktrees.
- Do not expose MLX servers to the public internet.
- Do not use `model=local` with `mlx_lm.server`; use the full model path.
- Do not let agents run destructive shell commands outside a disposable workspace.
- Do not auto-commit security, auth, payment, migration, or deployment changes.

See `docs/SETUP.md` and `docs/OPERATIONS.md` for the full setup and daily workflow.
