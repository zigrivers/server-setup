---
description: Audit the deployed two-Mac AI stack against the canonical HTML guide
argument-hint: [optional focus area]
allowed-tools: Read, Grep, Glob, Bash(ssh admin@10.10.10.2:*), Bash(launchctl print:*), Bash(launchctl list:*), Bash(claude mcp list), Bash(lsof -nP*), Bash(curl -s http://127.0.0.1:*), Bash(curl -s http://10.10.10.2:*), Bash(curl -fsS --max-time*), Bash(ping -c*), Bash(scripts/preflight.sh), Bash(scripts/m1-ai-status.sh), Bash(scripts/m2-ai-status.sh), Bash(scripts/smoke-test-endpoints.sh), Bash(cat:*), Bash(ls:*), Bash(test:*), Bash(git -C:*)
---

You are auditing the actual deployment of the two-Mac local AI stack
against the canonical procedure in `docs/html/local_ai_click_by_click_setup_guide.html`.

## Scope

- **Machine 1** (this Mac): inspect the filesystem directly.
- **Machine 2** (10.10.10.2): inspect via `ssh admin@10.10.10.2 '…'`.

If `$ARGUMENTS` is non-empty, focus the audit on that area; otherwise
run the full audit below.

## Process

1. **Start with the preflight script**, which already covers 8 baseline
   checks. From the repo root:
   ```bash
   scripts/preflight.sh
   ```
   Treat its output as authoritative for: TB ping, SSH, hf auth, M1
   venv import, all three endpoints up, `.env` keys present.

2. **For Machine 1, then verify these directly:**
   - `~/ai/local-ai-stack` exists and `git -C ~/ai/local-ai-stack status` is clean (or expected).
   - `~/ai/local-ai-stack/.venv/bin/local-ai-agents` and `local-exec-plan` exist.
   - `~/ai/bin/` has the expected symlinks (`start-orchestrator.sh`, `m1-ai-status.sh`, `smoke-test-endpoints.sh`, `bench-chat-endpoint.sh`, `preflight.sh`).
   - `~/Library/LaunchAgents/com.localai.orchestrator.plist` exists; `launchctl print "gui/$(id -u)/com.localai.orchestrator"` shows it loaded.
   - `~/.claude/skills/{delegate-local,local-review,local-ai-status}` exist with SKILL.md inside each.
   - `~/.gemini/antigravity-cli/skills/{delegate-local,local-review,local-ai-status}` exist with SKILL.md inside each.
   - `claude mcp list` shows `local-ai-delegate`.
   - `~/.gemini/antigravity-cli/mcp_config.json` contains `local-ai-delegate` configuration.
   - `~/.codex/config.toml` mentions `local-ai-delegate` with `tool_timeout_sec = 3600` (if Codex is configured).

3. **For Machine 2, verify via SSH:**
   - `ssh admin@10.10.10.2 'ls ~/ai/local-ai-stack/.venv/bin/mlx_lm.server'`
   - `ssh admin@10.10.10.2 'ls ~/ai/models/ | head'` includes the Developer and Reviewer model directories.
   - `ssh admin@10.10.10.2 'lsof -nP -iTCP:8002 -iTCP:8003 -sTCP:LISTEN'` shows both ports listening.
   - `ssh admin@10.10.10.2 'launchctl print gui/$(id -u)/com.localai.workers'` shows the agent loaded (if autostart is installed).
   - `ssh admin@10.10.10.2 'cat ~/Library/LaunchAgents/com.localai.workers.plist'` references `start-worker-models.sh`.

4. **Cross-check `.env`** at `~/ai/local-ai-stack/.env` against
   `configs/env.machine1.example` — call out any new keys in the
   template the user is missing, or any non-default values worth a
   sanity check.

## Output format

Produce a single Markdown report with three sections:

### Machine 1
| Check | Status | Remediation |
|---|---|---|
| ... | ✅ / ❌ | exact command to run |

### Machine 2
| Check | Status | Remediation |
|---|---|---|
| ... | ✅ / ❌ | exact command to run |

### Drift / notes
- Any `.env` keys missing from the user's file
- Any documented step in the HTML guide you couldn't verify and why
- Suggested next action

Be precise with paths and exact commands. The user should be able to
copy-paste each remediation cell verbatim. Do not invent fixes for
things you couldn't observe — say "could not verify" and explain why.

Focus area (if any): $ARGUMENTS
