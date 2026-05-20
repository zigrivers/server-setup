# Architecture

## System overview

```text
Machine 1 — Daily driver / control plane
  - Claude Code and Codex
  - VS Code / Cursor
  - LangGraph controller
  - MCP bridge
  - Orchestrator model on 127.0.0.1:8001

Thunderbolt Bridge
  Machine 1: 10.10.10.1
  Machine 2: 10.10.10.2

Machine 2 — Inference worker
  - Developer model on 10.10.10.2:8002
  - Reviewer model on 10.10.10.2:8003
  - optional MTP / Security Reviewer on 10.10.10.2:8004
```

## Endpoint map

| Role | Machine | Endpoint | Default model |
|---|---:|---|---|
| Orchestrator | Machine 1 | `http://127.0.0.1:8001/v1` | `Qwen3.6-35B-A3B Heretic BF16` |
| Developer | Machine 2 | `http://10.10.10.2:8002/v1` | `Qwen3.6-27B Heretic2 NEO-CODE mixed-9.4bit` |
| Reviewer | Machine 2 | `http://10.10.10.2:8003/v1` | `Qwen3.6-27B Heretic BF16` |
| Experimental | Machine 2 | `http://10.10.10.2:8004/v1` | MTP-preserved 35B-A3B candidate |

## Why split Orchestrator onto Machine 1?

Machine 1 is already the cockpit: it runs Claude Code, Codex, VS Code/Cursor, the MCP bridge, git worktrees, and LangGraph. Running the Orchestrator locally keeps planning/routing close to the tools and frees Machine 2 for execution-heavy models.

Machine 2 should be treated as a model execution appliance: Developer, Reviewer, optional Security Reviewer, optional Kimi/MTP experiments.

## Data flow

```text
User
  ↓
Claude Code / Codex creates plan
  ↓
Plan saved in plans/*.md
  ↓
MCP bridge or CLI invokes local-exec-plan
  ↓
LangGraph Orchestrator creates execution plan
  ↓
Developer writes patch and test commands
  ↓
Controller applies patch inside worktree
  ↓
Reviewer approves or sends feedback
  ↓
Loop until approved or max iterations
  ↓
Frontier model does final review
  ↓
Human merges
```

## Important implementation detail

`mlx_lm.server` expects the `model` value in chat requests to be an actual model path or Hugging Face repo ID. It does not understand arbitrary aliases like `local` or `default` unless you put a proxy in front of it.
