# Repo Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `~/Developer/server-setup` the single source of truth for the two-Mac local AI stack: re-point all deployed tooling (symlinks, MCP registrations, skills) at it, bring both runtime clones to head, fix the missing Codex MCP entry, update the stale audit doc, and archive the old `~/Documents/dev-projects/server-setup` copy.

**Architecture:** No change to the two-machine architecture. M1 keeps the orchestrator LaunchAgent running from `~/ai/local-ai-stack`; M2 keeps the per-worker LaunchDaemons. Only the *control-plane plumbing on M1* moves: which checkout the `~/ai/bin` symlinks, the `local-ai-delegate` MCP server, and the installed skills point to.

**Tech Stack:** bash, git, uv (Python 3.12 venv), launchctl, `claude mcp` / `codex mcp` CLIs.

---

## Non-goals

- No redesign of the two-machine architecture.
- No model changes, no Docker (ruled out: no Metal GPU passthrough in containers on macOS).
- No restart of M2 inference daemons (the pending commits touch only docs/installer scripts, verified in Task 7).
- No deletion of the Documents copy — archive only.

## Current system summary (audited 2026-06-12)

- Stack is healthy: orchestrator on `127.0.0.1:8001`, developer on `10.10.10.2:8002`, reviewer on `10.10.10.2:8003`, all serving. M1 LaunchAgent `com.localai.orchestrator` running; M2 system LaunchDaemons `com.localai.developer` / `com.localai.reviewer` running.
- **Three checkouts of `github.com/zigrivers/server-setup`:**
  1. `~/Developer/server-setup` — newest, at `ad8a51b` (5 commits ahead of deployed), has untracked plans + duplicate `* 2` files. **No `.venv`.**
  2. `~/Documents/dev-projects/server-setup` — at `4a6220c`, has its own untracked files. All 11 `~/ai/bin` symlinks and the Claude `local-ai-delegate` MCP registration (user scope) point here.
  3. `~/ai/local-ai-stack` on both machines — runtime clones, clean at `4a6220c`. launchd plists execute scripts from here.
- Antigravity `~/.gemini/antigravity-cli/mcp_config.json` already points at `~/Developer/server-setup/.venv/bin/python` — **which does not exist**, so Antigravity delegation is broken.
- `~/.codex/config.toml` has no `local-ai-delegate` entry — Codex cannot delegate at all.
- `.claude/commands/audit-stack.md:43-44` still checks the retired `com.localai.workers` gui LaunchAgent on M2 (replaced by per-worker LaunchDaemons in `628dec2`/`0d96149`).
- Verified identical/stale duplicates in Developer copy: `scripts/audit-stack 2.sh`, `scripts/fix-stack 2.sh` (byte-identical to originals), `.claude/settings 2.json` (older subset of `settings.json`).
- All installer scripts (`install-symlinks.sh`, `register-mcp-claude.sh`, `register-mcp-codex.sh`, `install-claude-skills.sh`, `install-antigravity-skills.sh`) compute `REPO_DIR` from their own location, so running them from the Developer copy re-points everything.

## Proposed architecture (after)

- `~/Developer/server-setup` = single editable source of truth; has `.venv` (py3.12, `local-ai-stack` installed editable).
- `~/ai/bin/*` symlinks → `~/Developer/server-setup/scripts/*`.
- Claude + Codex + Antigravity MCP all run `~/Developer/server-setup/.venv/bin/python ~/Developer/server-setup/mcp/local_delegate_mcp/server.py`.
- `~/ai/local-ai-stack` on both machines = deploy targets, fast-forwarded to `origin/main` head; launchd plists unchanged.
- `~/Documents/dev-projects/server-setup` → renamed to `server-setup.archived-2026-06-12`.

## Files expected to change

| File | Change |
|---|---|
| `scripts/audit-stack 2.sh`, `scripts/fix-stack 2.sh`, `.claude/settings 2.json` | delete (verified duplicates) |
| `.gitignore` | add `.antigravitycli/` |
| `plans/2026-05-21-*.md` (4 files), `plans/2026-05-22-server-setup-debates-assessment.md`, `docs/html/server_setup_debates_assessment.html`, this plan | commit |
| `.claude/commands/audit-stack.md` | replace `com.localai.workers` checks with per-worker LaunchDaemon checks |
| `~/ai/bin/*` (11 symlinks) | re-point (outside repo) |
| `~/.claude.json` user-scope MCP entry | re-register (outside repo) |
| `~/.codex/config.toml` | add `[mcp_servers.local-ai-delegate]` (outside repo) |
| `~/ai/local-ai-stack` on M1 + M2 | `git pull --ff-only` |

---

### Task 1: Delete verified duplicates, ignore `.antigravitycli/`

**Files:**
- Delete: `scripts/audit-stack 2.sh`, `scripts/fix-stack 2.sh`, `.claude/settings 2.json`
- Modify: `.gitignore`

- [ ] **Step 1: Re-verify the duplicates are still redundant** (they were on 2026-06-12; re-check in case of edits since)

```bash
cd ~/Developer/server-setup
diff "scripts/audit-stack 2.sh" scripts/audit-stack.sh && echo OK1
diff "scripts/fix-stack 2.sh" scripts/fix-stack.sh && echo OK2
diff ".claude/settings 2.json" .claude/settings.json | head -5
```

Expected: `OK1`, `OK2`; the settings diff shows `settings 2.json` is missing permissions that `settings.json` has (older subset). If any diff shows content that exists ONLY in a `* 2` file, STOP and merge it manually before deleting.

- [ ] **Step 2: Delete the duplicates**

```bash
cd ~/Developer/server-setup
rm "scripts/audit-stack 2.sh" "scripts/fix-stack 2.sh" ".claude/settings 2.json"
```

- [ ] **Step 3: Ignore the tool-generated `.antigravitycli/` directory** (contains only a symlink into `~/.gemini/config`; machine-local, not repo content)

```bash
cd ~/Developer/server-setup
printf '\n# Antigravity CLI local state\n.antigravitycli/\n' >> .gitignore
git status --short
```

Expected: no `* 2` files, no `.antigravitycli/` in output; remaining untracked = plans + `docs/html/server_setup_debates_assessment.html`.

- [ ] **Step 4: Commit**

```bash
cd ~/Developer/server-setup
git add .gitignore
git commit -m "chore: ignore .antigravitycli local state, drop duplicate ' 2' files"
```

### Task 2: Salvage untracked work from the Documents copy, commit all plans

**Files:**
- Create/Modify: `plans/2026-05-21-commit-and-cleanup.md`, `plans/2026-05-21-env-username-note.md`, `plans/2026-05-21-launchd-source-edits.md`, `plans/2026-05-21-launchd-survive-reboot-and-crashes.md`, `plans/2026-05-22-server-setup-debates-assessment.md`, `docs/html/server_setup_debates_assessment.html`

- [ ] **Step 1: Diff each untracked plan that exists in both copies**

```bash
OLD=~/Documents/dev-projects/server-setup
NEW=~/Developer/server-setup
for f in "plans/2026-05-21-commit-and-cleanup.md" "plans/2026-05-21-launchd-survive-reboot-and-crashes.md"; do
  echo "=== $f ==="; diff "$OLD/$f" "$NEW/$f"
done
```

Decision rule: keep whichever version contains the LaunchDaemon-era content (mentions `com.localai.developer`/`com.localai.reviewer` or `LaunchDaemons`); if both add distinct content, append the Documents-only sections into the Developer file. If identical apart from whitespace, keep the Developer version.

- [ ] **Step 2: Copy any Documents-only untracked plans into Developer** (skip files already identical)

```bash
for f in "plans/2026-05-21-env-username-note.md" "plans/2026-05-21-launchd-source-edits.md"; do
  [ -f "$NEW/$f" ] || cp "$OLD/$f" "$NEW/$f"
done
```

- [ ] **Step 3: Commit and push everything**

```bash
cd ~/Developer/server-setup
git add plans/ docs/html/server_setup_debates_assessment.html
git commit -m "docs: commit accumulated plans and debates assessment"
git push origin main
```

Expected: push succeeds; `git status` clean except this plan file (committed in Task 3) and `## main...origin/main` up to date.

### Task 3: Update `audit-stack.md` for per-worker LaunchDaemons

**Files:**
- Modify: `.claude/commands/audit-stack.md:43-44`

- [ ] **Step 1: Replace the two stale M2 checks.** Current lines 43–44:

```markdown
   - `ssh admin@10.10.10.2 'launchctl print gui/$(id -u)/com.localai.workers'` shows the agent loaded (if autostart is installed).
   - `ssh admin@10.10.10.2 'cat ~/Library/LaunchAgents/com.localai.workers.plist'` references `start-worker-models.sh`.
```

Replace with:

```markdown
   - `ssh admin@10.10.10.2 'launchctl print system/com.localai.developer'` shows `state = running`.
   - `ssh admin@10.10.10.2 'launchctl print system/com.localai.reviewer'` shows `state = running`.
   - `ssh admin@10.10.10.2 'cat /Library/LaunchDaemons/com.localai.developer.plist'` references `start-developer.sh`.
   - `ssh admin@10.10.10.2 'cat /Library/LaunchDaemons/com.localai.reviewer.plist'` references `start-reviewer.sh`.
```

- [ ] **Step 2: Verify no other stale references remain**

```bash
cd ~/Developer/server-setup
grep -rn 'com.localai.workers' .claude/ docs/ scripts/ || echo CLEAN
```

Expected: `CLEAN`, or only hits inside `docs/html/local_ai_click_by_click_setup_guide.html` historical sections — if the guide still *instructs* installing `com.localai.workers`, update those instructions to match `scripts/install-launchd-machine2.sh` (which installs the per-worker LaunchDaemons).

- [ ] **Step 3: Commit and push**

```bash
cd ~/Developer/server-setup
git add .claude/commands/audit-stack.md plans/2026-06-12-consolidate-repo-copies.md
git commit -m "docs: audit-stack checks per-worker LaunchDaemons on Machine 2; add consolidation plan"
git push origin main
```

### Task 4: Create `.venv` in the Developer copy

This is the step that un-breaks Antigravity (its `mcp_config.json` already points here).

**Files:**
- Create: `~/Developer/server-setup/.venv/` (gitignored)

- [ ] **Step 1: Create venv and install the package editable**

```bash
cd ~/Developer/server-setup
uv venv .venv --python 3.12
uv pip install -e . --python .venv/bin/python
```

- [ ] **Step 2: Verify import and entry points**

```bash
~/Developer/server-setup/.venv/bin/python -c 'import local_ai_stack; print("import ok")'
ls ~/Developer/server-setup/.venv/bin/local-ai-agents ~/Developer/server-setup/.venv/bin/local-exec-plan
```

Expected: `import ok` and both binaries listed.

- [ ] **Step 3: Verify the MCP server starts under this venv** (it speaks stdio JSON-RPC; a clean handshake-wait then timeout-kill is success)

```bash
timeout 5 ~/Developer/server-setup/.venv/bin/python ~/Developer/server-setup/mcp/local_delegate_mcp/server.py < /dev/null; echo "exit=$?"
```

Expected: no Python traceback. `exit=124` (timeout while waiting for stdio input) or `exit=0` are both fine; an ImportError is a failure.

### Task 5: Re-point `~/ai/bin` symlinks

- [ ] **Step 1: Run the installer from the Developer copy**

```bash
cd ~/Developer/server-setup
scripts/install-symlinks.sh
```

- [ ] **Step 2: Verify all 11 symlinks point at the Developer copy**

```bash
readlink ~/ai/bin/* | sort
readlink ~/ai/bin/* | grep -c 'Developer/server-setup'
```

Expected: second command prints `11`; no path contains `Documents/dev-projects`.

### Task 6: Re-register the Claude MCP server

- [ ] **Step 1: Remove the old user-scope registration**

```bash
claude mcp remove "local-ai-delegate" -s user
```

- [ ] **Step 2: Re-register from the Developer copy**

```bash
cd ~/Developer/server-setup
scripts/register-mcp-claude.sh
```

- [ ] **Step 3: Verify**

```bash
claude mcp get local-ai-delegate
```

Expected: `Status: ✔ Connected`; `Command:` and `Args:` paths under `/Users/kenallred/Developer/server-setup/`; `LOCAL_EXEC_PLAN_BIN` likewise. Note: connection is checked by new sessions — if `get` shows the right paths but not yet connected, that's fine until the next Claude session.

### Task 7: Register the Codex MCP server

- [ ] **Step 1: Register**

```bash
cd ~/Developer/server-setup
scripts/register-mcp-codex.sh
```

- [ ] **Step 2: Add timeouts to `~/.codex/config.toml`.** Find the `[mcp_servers.local-ai-delegate]` block the previous step created and add these two lines inside it (the script prints this reminder):

```toml
startup_timeout_sec = 20
tool_timeout_sec = 3600
```

- [ ] **Step 3: Verify**

```bash
codex mcp list
grep -A3 'mcp_servers.local-ai-delegate' ~/.codex/config.toml | grep tool_timeout_sec
```

Expected: `local-ai-delegate` listed; `tool_timeout_sec = 3600` printed.

### Task 8: Refresh installed skills from the Developer copy

The installed skills in `~/.claude/skills/` and `~/.gemini/antigravity-cli/skills/` are copies (dated May 23). Refresh so they match head.

- [ ] **Step 1: Run both installers**

```bash
cd ~/Developer/server-setup
scripts/install-claude-skills.sh
scripts/install-antigravity-skills.sh
```

- [ ] **Step 2: Verify**

```bash
for s in delegate-local local-review local-ai-status; do
  ls ~/.claude/skills/$s/SKILL.md ~/.gemini/antigravity-cli/skills/$s/SKILL.md
done
```

Expected: all six SKILL.md paths listed, no errors.

### Task 9: Fast-forward both runtime clones

- [ ] **Step 1: Confirm the pending commits don't touch launchd-executed scripts** (so no daemon restarts are needed)

```bash
git -C ~/Developer/server-setup diff --stat 4a6220c..origin/main -- scripts/start-orchestrator.sh scripts/start-developer.sh scripts/start-reviewer.sh scripts/start-worker-models.sh
```

Expected: empty output. **If not empty:** the orchestrator/worker restart becomes necessary — stop here and get explicit approval before restarting inference services.

- [ ] **Step 2: Pull on M1**

```bash
git -C ~/ai/local-ai-stack pull --ff-only
git -C ~/ai/local-ai-stack log --oneline -1
```

Expected: fast-forward to the same SHA as `git -C ~/Developer/server-setup rev-parse --short HEAD`.

- [ ] **Step 3: Pull on M2**

```bash
ssh admin@10.10.10.2 'git -C ~/ai/local-ai-stack pull --ff-only && git -C ~/ai/local-ai-stack log --oneline -1'
```

Expected: same SHA as M1.

- [ ] **Step 4: Confirm services were untouched**

```bash
curl -s --max-time 5 http://127.0.0.1:8001/v1/models | head -c 100; echo
curl -s --max-time 5 http://10.10.10.2:8002/v1/models | head -c 100; echo
curl -s --max-time 5 http://10.10.10.2:8003/v1/models | head -c 100; echo
```

Expected: three JSON `{"object": "list", ...}` responses.

### Task 10: Full verification, then archive the Documents copy

- [ ] **Step 1: Preflight must pass clean now**

```bash
cd ~/Developer/server-setup
scripts/preflight.sh
```

Expected: `=== preflight: PASS ===` with all 8 checks `[ok]` (the previously failing `.venv` check now passes).

- [ ] **Step 2: Smoke-test endpoints**

```bash
cd ~/Developer/server-setup
scripts/smoke-test-endpoints.sh
```

Expected: success output for orchestrator, developer, reviewer.

- [ ] **Step 3: Verify nothing still references the Documents copy**

```bash
claude mcp get local-ai-delegate | grep -c 'Documents/dev-projects' || echo CLAUDE-CLEAN
readlink ~/ai/bin/* | grep -c 'Documents/dev-projects' || echo SYMLINKS-CLEAN
grep -c 'Documents/dev-projects/server-setup' ~/.codex/config.toml ~/.gemini/antigravity-cli/mcp_config.json || echo CONFIGS-CLEAN
```

Expected: `CLAUDE-CLEAN`, `SYMLINKS-CLEAN`, and for configs either `CONFIGS-CLEAN` or only the pre-existing `[projects."..."]` trust entry in `config.toml` (harmless; leave it).

- [ ] **Step 4: Check the Documents copy for anything not yet salvaged, then archive**

```bash
git -C ~/Documents/dev-projects/server-setup status --short
mv ~/Documents/dev-projects/server-setup ~/Documents/dev-projects/server-setup.archived-2026-06-12
```

Gate: only run the `mv` if Step 1–3 all passed and `status --short` shows nothing beyond the files already salvaged in Tasks 1–2. Do NOT `rm -rf`.

- [ ] **Step 5: End-to-end delegate sanity check.** Per the known failure mode, do not trust "Approved: True" — verify actual commits. From a fresh Claude session, run the `local-ai-status` skill (or call the `local_ai_status` MCP tool), then a trivial `/delegate-local` task, and confirm with `git -C <worktree> log --oneline` that real commits exist.

---

## Acceptance criteria

1. `scripts/preflight.sh` from `~/Developer/server-setup` prints `PASS` with 8/8 `[ok]`.
2. `claude mcp get local-ai-delegate`, `codex mcp list`, and `~/.gemini/antigravity-cli/mcp_config.json` all resolve to existing files under `~/Developer/server-setup/` (Codex with `tool_timeout_sec = 3600`).
3. All 11 `~/ai/bin` symlinks resolve into `~/Developer/server-setup/scripts/`.
4. `~/ai/local-ai-stack` on M1 and M2 at the same SHA as `origin/main` head; all three endpoints still serving.
5. `git -C ~/Developer/server-setup status` clean; `audit-stack.md` checks per-worker LaunchDaemons.
6. `~/Documents/dev-projects/server-setup` no longer exists at its old path (archived).

## Test plan

Verification is embedded per-task (each task ends with a command + expected output). The end-to-end test is Task 10: preflight, smoke test, no-stale-references grep, and a real delegate round-trip with commit verification.

## Rollback plan

- Symlinks: `cd ~/Documents/dev-projects/server-setup.archived-2026-06-12 && scripts/install-symlinks.sh` (re-points back).
- Claude MCP: `claude mcp remove local-ai-delegate -s user && cd ~/Documents/dev-projects/server-setup.archived-2026-06-12 && scripts/register-mcp-claude.sh`.
- Codex: `codex mcp remove local-ai-delegate` (or delete the TOML block).
- Runtime clones: `git -C ~/ai/local-ai-stack reset --hard 4a6220c` (both machines) — only if a pulled change misbehaves; services themselves were never restarted.
- Archive: `mv ~/Documents/dev-projects/server-setup.archived-2026-06-12 ~/Documents/dev-projects/server-setup`.
- Repo commits are docs/chore only; revert with `git revert <sha>` if needed.

## Docs updates

- `.claude/commands/audit-stack.md` — Task 3 (LaunchDaemon checks).
- If Task 3 Step 2 finds the click-by-click HTML guide still instructing the old `com.localai.workers` install, update that section to match `scripts/install-launchd-machine2.sh`.
- This plan file committed in Task 3.

## Risks and edge cases

- **Open Claude/Codex sessions** hold the old MCP server process; re-registration takes effect on next session start. Mitigate: restart sessions after Task 7.
- **A delegate job running mid-cutover** would execute from the old venv. Mitigate: do Tasks 5–7 when no delegation is in flight.
- **`uv pip install -e .` dependency drift**: the new venv installs current `pyproject.toml` deps, which may be newer than the Documents venv's frozen state. If the MCP server errors on import (Task 4 Step 3 catches this), pin versions to match `~/Documents/dev-projects/server-setup/.venv` via `uv pip freeze --python ~/Documents/dev-projects/server-setup/.venv/bin/python`.
- **Documents-copy untracked plans may contain unique content** — Task 2's diff step exists precisely to catch this before archive.
- **M2 pull failure (diverged clone)**: `--ff-only` will refuse rather than merge; if it refuses, inspect `git -C ~/ai/local-ai-stack status` on M2 — do not force-reset without checking for local edits.
- **Codex `[projects]` trust entry** for the Documents path remains in `config.toml` after archive; harmless, but the archived path is no longer trusted-relevant. Leave as-is.
