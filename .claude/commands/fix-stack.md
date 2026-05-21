---
description: Audit the deployed two-Mac stack and remediate fixable drift, with explicit gates for anything destructive
argument-hint: [optional focus area]
allowed-tools: Read, Grep, Glob, Bash(ssh admin@10.10.10.2:*), Bash(launchctl print:*), Bash(launchctl list:*), Bash(claude mcp list), Bash(lsof -nP*), Bash(curl -s http://127.0.0.1:*), Bash(curl -s http://10.10.10.2:*), Bash(curl -fsS --max-time*), Bash(ping -c*), Bash(scripts/preflight.sh), Bash(scripts/m1-ai-status.sh), Bash(scripts/m2-ai-status.sh), Bash(scripts/smoke-test-endpoints.sh), Bash(scripts/install-symlinks.sh), Bash(scripts/install-claude-skills.sh), Bash(scripts/install-launchd-machine1.sh), Bash(scripts/install-launchd-machine2.sh), Bash(scripts/start-orchestrator.sh), Bash(scripts/start-worker-models.sh), Bash(scripts/stop-orchestrator.sh), Bash(scripts/stop-worker-models.sh), Bash(uv pip install*), Bash(uv venv*), Bash(git -C * pull), Bash(git -C * status*), Bash(cat:*), Bash(ls:*), Bash(test:*)
---

You are the remediator for the two-Mac local AI stack. Compare the
deployed state against the canonical procedure in
`docs/html/local_ai_click_by_click_setup_guide.html` and **fix what you
safely can**.

Inspect Machine 1 directly. Inspect Machine 2 via
`ssh admin@10.10.10.2 '…'`. **Never run an install or write command on
Machine 2 over SSH without asking the user first**, even if your
allowlist would let you — Machine 2 has bigger blast radius.

## Triage rules

For each failing check, classify into exactly one bucket and act
accordingly:

### Bucket 1 — Auto-safe (just run it)

Idempotent scripts that fix the issue cleanly even if they ran before:

- Missing `~/ai/bin` symlinks → `scripts/install-symlinks.sh`
- Repo venv missing → `uv venv .venv --python 3.12`
- Repo package not installed → `uv pip install -e '.[all]'` (M1) or `'.[mlx]'` (M2 via the user, not over SSH)
- Repo out of date with origin → `git -C ~/ai/local-ai-stack pull`
- Claude skills not installed → `scripts/install-claude-skills.sh`
- M1 LaunchAgent not loaded → `scripts/install-launchd-machine1.sh` (the install script handles the bootout/bootstrap reload)
- Orchestrator/workers stopped → `scripts/start-orchestrator.sh` / `scripts/start-worker-models.sh`

Run these without asking. Report each as ✅ **fixed**.

### Bucket 2 — Approve-then-run (one-line ask)

Idempotent but visible / state-changing. Show the exact command and
ask "Run this? y/N" before executing:

- `scripts/register-mcp-claude.sh` (errors if already registered; remedy is `claude mcp remove local-ai-delegate` then rerun)
- `scripts/register-mcp-codex.sh`
- `scripts/install-launchd-machine2.sh` (would run on this Mac if you're auditing from M2; if you're on M1 and M2 needs autostart, this is a Bucket 4 item)
- `stop-orchestrator.sh` / `stop-worker-models.sh` followed by a `start-*.sh` (restart cycle)

### Bucket 3 — Long-running, ask first

The action itself is fine but the cost is real:

- `hf download` (model fetches, 200+ GB cumulative)
- Full reinstall of the venv from scratch (10–15 min)
- Anything that touches `~/ai/models/`

Surface the cost and the command, ask before running.

### Bucket 4 — Human-only (do not attempt)

- `.env` missing or has wrong keys → tell the user to `cp configs/env.machine1.example .env` (would overwrite their edits if they have any)
- HF token expired → tell the user to run `hf auth login`
- Different Machine 2 short username → tell the user to edit `.claude/settings.json` allowlist
- Any **install/remediation script that needs to run ON Machine 2** → tell the user to run it on Machine 2 directly (or via `ssh admin@10.10.10.2 'cd ~/ai/local-ai-stack && scripts/...'` after they explicitly approve)
- macOS prep items (sleep settings, iCloud, FileVault) → tell the user
- Hardware (Thunderbolt cable, IPs) → tell the user

For each, print the exact command or System Settings path. **Do not
run it.**

## Process

1. Run `scripts/preflight.sh` first — it's the fastest signal for what
   broad category of thing is wrong (network, auth, endpoints, env).
2. Walk the same checklist as `/audit-stack`:
   - **Machine 1**: repo present, venv with package, `~/ai/bin` symlinks, LaunchAgent loaded, Claude skills present, MCP registered, `.env` valid, endpoints reachable.
   - **Machine 2** (over SSH, **read-only**): repo present, venv with `mlx_lm.server`, models present, ports 8002/8003 listening, LaunchAgent loaded.
3. For each ❌, run the triage above.

## Output format

Produce a Markdown report. **One section per machine**, each with a
table:

| Check | Before | Action taken | After |
|---|---|---|---|
| `~/ai/bin/start-orchestrator.sh` symlink | ❌ missing | ran `scripts/install-symlinks.sh` | ✅ present |
| MCP registered | ❌ not in `claude mcp list` | 📋 pending: run `scripts/register-mcp-claude.sh` (Bucket 2) | — |
| Machine 2 launchd | ❌ not loaded | 👤 needs human: `ssh admin@10.10.10.2 'cd ~/ai/local-ai-stack && scripts/install-launchd-machine2.sh'` | — |

Status icons:
- ✅ **fixed** — Bucket 1 action ran and resolved the issue
- 📋 **pending** — Bucket 2/3 action proposed, awaiting user approval
- 👤 **needs human** — Bucket 4 action; user must do it themselves
- ⚠️ **failed** — auto-fix attempted but the issue persists (include error)

End with a **Next actions** summary: numbered list of every 📋 and 👤
item, with the exact command, in the order the user should run them.

Be conservative. If you're not sure which bucket a fix belongs to,
treat it as Bucket 2 and ask.

Focus area (if any): $ARGUMENTS
