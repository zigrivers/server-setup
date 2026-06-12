# Plan: launchd reboot/crash-restart — source edits only (Phase B)

> This is a scoped sub-plan that contains ONLY the source-edit tasks from
> `plans/2026-05-21-launchd-survive-reboot-and-crashes.md`. The deploy
> tasks (Tasks 7, 8, 9 of the parent plan) are deliberately excluded —
> they touch live services and are executed by the frontier architect
> after merging this work.
>
> **Do NOT run any of:**
> - `scripts/install-launchd-machine1.sh`
> - `scripts/install-launchd-machine2.sh`
> - `scripts/start-orchestrator.sh` / `start-worker-models.sh` / `start-developer.sh` / `start-reviewer.sh`
> - `scripts/stop-orchestrator.sh` / `stop-worker-models.sh`
> - `launchctl ...`, `sudo ...`, `kill ...`, `ssh ...`, `git push`, `gh ...`
>
> All work happens in a separate git worktree on a feature branch. The
> frontier reviewer will inspect the worktree diff and merge it before
> any live deploy.

## Goal
Land six source/doc changes that make the local AI stack survive reboot
(M1 LaunchAgent, M2 LaunchDaemons) and auto-restart on crash. No live
system changes here — only repository edits.

## Non-goals
- No deploy. No running install scripts. No launchctl, sudo, ssh, kill, gh, or git push.
- No changes to model choices, ports, hosts.
- No HTML guide updates (a separate follow-up).

## Current system summary
- `scripts/start-orchestrator.sh` ends with `nohup mlx_lm.server ... &` (forks and exits). Needs `exec` so launchd tracks a real PID.
- `scripts/start-worker-models.sh` starts BOTH workers via `nohup ... &`. One launchd plist can supervise only one PID, so Machine 2 needs two per-worker scripts.
- `configs/launchd/com.localai.orchestrator.plist.template` has `KeepAlive=false`. Needs a dict variant for crash-restart.
- `configs/launchd/com.localai.workers.plist.template` is a single combined LaunchAgent — being replaced by two LaunchDaemon templates.
- `scripts/install-launchd-machine1.sh` writes the plist but doesn't `chmod 644` the result.
- `scripts/install-launchd-machine2.sh` will be rewritten end-to-end to install LaunchDaemons via sudo.

## Proposed architecture
Same as the parent plan:
- M1 orchestrator stays a LaunchAgent (loads at user login on the daily-driver Mac).
- M2 workers become two LaunchDaemons (`com.localai.developer`, `com.localai.reviewer`) in `/Library/LaunchDaemons/`, root:wheel, running as user `admin` via `UserName=admin`. Loads at boot, no login required.
- All three plists use `KeepAlive` dict (`SuccessfulExit=false`, `Crashed=true`), `ThrottleInterval=60`, `ProcessType=Interactive`.
- Launcher scripts `exec` instead of `nohup ... &` so launchd tracks the real worker PID.

## Files expected to change
- Modify: `scripts/start-orchestrator.sh`
- Modify: `configs/launchd/com.localai.orchestrator.plist.template`
- Modify: `scripts/install-launchd-machine1.sh`
- Create: `scripts/start-developer.sh`
- Create: `scripts/start-reviewer.sh`
- Modify: `scripts/start-worker-models.sh`
- Create: `configs/launchd/com.localai.developer.plist.template`
- Create: `configs/launchd/com.localai.reviewer.plist.template`
- Delete: `configs/launchd/com.localai.workers.plist.template`
- Rewrite: `scripts/install-launchd-machine2.sh`
- Modify: `docs/OPERATIONS.md`

## Step-by-step implementation tasks

### Task A — Convert `scripts/start-orchestrator.sh` to `exec`

Replace the tail of the script (the `nohup ... &` block plus the `echo "Started."` line) with:

```bash
echo "Log: $HOME/ai/logs/orchestrator.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  >> "$HOME/ai/logs/orchestrator.log" 2>&1
```

Notes for the implementer:
- Use `>>` (append) not `>` (truncate) so log history survives restarts.
- The line after `exec` is unreachable; delete the old "Started." echo.
- Keep everything above the `nohup` (venv source, env load, port precheck) exactly as-is.

Verify:
```bash
bash -n scripts/start-orchestrator.sh
```

Commit:
```
Use exec in start-orchestrator.sh so launchd tracks the real worker PID
```

### Task B — Update orchestrator plist template + install script

File: `configs/launchd/com.localai.orchestrator.plist.template`

Replace the lines:
```xml
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
```
with:
```xml
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>Crashed</key><true/>
  </dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>ProcessType</key><string>Interactive</string>
```

File: `scripts/install-launchd-machine1.sh`

After the line:
```bash
sed "s|__HOME__|$HOME|g" "$SRC" > "$DEST"
```
insert (a new line, same indentation):
```bash
chmod 644 "$DEST"
```

Verify:
```bash
plutil -lint configs/launchd/com.localai.orchestrator.plist.template
bash -n scripts/install-launchd-machine1.sh
```

Commit:
```
Enable crash-restart for orchestrator launchd agent (KeepAlive dict, ThrottleInterval 60, chmod 644)
```

### Task C — Create per-worker launcher scripts; rewrite combined wrapper

Create `scripts/start-developer.sh` (mode 755) with:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
source "$REPO_DIR/.venv/bin/activate"
mkdir -p "$HOME/ai/logs"

if [ -f "$REPO_DIR/.env" ]; then
  set -a; source "$REPO_DIR/.env"; set +a
fi

HOST="${WORKER_HOST:-10.10.10.2}"
PORT="${DEV_PORT:-8002}"
MODEL="${DEV_MODEL_PATH:-$HOME/ai/models/developer-qwen36-27b-heretic2-mixed94}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already listening on port $PORT:"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  exit 1
fi

echo "Starting Developer on $HOST:$PORT (model: $MODEL)"
echo "Log: $HOME/ai/logs/developer.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  >> "$HOME/ai/logs/developer.log" 2>&1
```

Create `scripts/start-reviewer.sh` (mode 755) — identical shape but with:
- `PORT="${REVIEW_PORT:-8003}"`
- `MODEL="${REVIEW_MODEL_PATH:-$HOME/ai/models/reviewer-qwen36-27b-heretic-bf16}"`
- log file `$HOME/ai/logs/reviewer.log`
- echo text says "Reviewer" instead of "Developer"

Rewrite `scripts/start-worker-models.sh` (keep shebang + `set -euo pipefail`) so its body becomes:

```bash
# Manual-mode launcher. Normally launchd owns these via
#   com.localai.developer and com.localai.reviewer  (LaunchDaemons on M2).
# Use this script only when you've intentionally booted the launchd
# daemons out (e.g. during debugging).

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
"$REPO_DIR/scripts/start-developer.sh" &
DEV_PID=$!
"$REPO_DIR/scripts/start-reviewer.sh" &
REV_PID=$!

echo "Developer  pid=$DEV_PID  log=$HOME/ai/logs/developer.log"
echo "Reviewer   pid=$REV_PID  log=$HOME/ai/logs/reviewer.log"
echo "Note: these run in the background; launchd is not supervising them."
```

Verify:
```bash
chmod +x scripts/start-developer.sh scripts/start-reviewer.sh
bash -n scripts/start-developer.sh
bash -n scripts/start-reviewer.sh
bash -n scripts/start-worker-models.sh
```

Commit:
```
Split Machine 2 workers into per-worker exec launchers
```

### Task D — Create LaunchDaemon plist templates; delete combined LaunchAgent template

Create `configs/launchd/com.localai.developer.plist.template` with the EXACT content:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- LaunchDaemon template. install-launchd-machine2.sh replaces
     __USER__ with the Machine 2 worker username (admin) and __HOME__
     with that user's home (/Users/admin), then installs the rendered
     plist into /Library/LaunchDaemons/ with sudo. Owned by root:wheel,
     mode 644. Loads at boot via `sudo launchctl bootstrap system ...`. -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.localai.developer</string>
  <key>UserName</key><string>__USER__</string>
  <key>GroupName</key><string>staff</string>
  <key>WorkingDirectory</key><string>__HOME__</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>__HOME__</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin</string>
  </dict>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>__HOME__/ai/local-ai-stack/scripts/start-developer.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>Crashed</key><true/>
  </dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>__HOME__/ai/logs/developer-launchd.out</string>
  <key>StandardErrorPath</key><string>__HOME__/ai/logs/developer-launchd.err</string>
</dict>
</plist>
```

Create `configs/launchd/com.localai.reviewer.plist.template` with the same shape, but:
- Label `com.localai.reviewer`
- Script path `__HOME__/ai/local-ai-stack/scripts/start-reviewer.sh`
- Stdout `__HOME__/ai/logs/reviewer-launchd.out`
- Stderr `__HOME__/ai/logs/reviewer-launchd.err`
- Comment block at the top can be shorter: `<!-- LaunchDaemon template. See the developer template for the substitution / install / load semantics. -->`

Delete `configs/launchd/com.localai.workers.plist.template`:
```bash
git rm configs/launchd/com.localai.workers.plist.template
```

Verify:
```bash
plutil -lint configs/launchd/com.localai.developer.plist.template
plutil -lint configs/launchd/com.localai.reviewer.plist.template
```

Commit:
```
Replace combined workers LaunchAgent with per-worker LaunchDaemon templates
```

### Task E — Rewrite `scripts/install-launchd-machine2.sh` for LaunchDaemons

Replace the body of `scripts/install-launchd-machine2.sh` (keep the shebang and `set -euo pipefail`) with EXACTLY this:

```bash
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DAEMON_DIR="/Library/LaunchDaemons"
UID_NUM="$(id -u)"
WORKER_USER="${WORKER_USER:-$(id -un)}"   # default to current user (admin on M2)
WORKER_HOME="${WORKER_HOME:-$HOME}"

mkdir -p "$HOME/ai/logs"

# --- Phase 1: bootout/remove the obsolete com.localai.workers LaunchAgent ---
OLD_LABEL="com.localai.workers"
OLD_AGENT_DEST="$HOME/Library/LaunchAgents/${OLD_LABEL}.plist"
for DOMAIN in "gui/$UID_NUM" "user/$UID_NUM"; do
  if launchctl print "$DOMAIN/$OLD_LABEL" >/dev/null 2>&1; then
    echo "Unloading obsolete $DOMAIN/$OLD_LABEL"
    launchctl bootout "$DOMAIN/$OLD_LABEL" || true
  fi
done
if [ -f "$OLD_AGENT_DEST" ]; then
  echo "Removing obsolete $OLD_AGENT_DEST"
  rm -f "$OLD_AGENT_DEST"
fi

# --- Phase 2: install LaunchDaemons under sudo ---
echo "Installing LaunchDaemons (sudo required)..."
sudo -v

install_daemon() {
  local LABEL="$1"
  local SRC="$REPO_DIR/configs/launchd/${LABEL}.plist.template"
  local DEST="$DAEMON_DIR/${LABEL}.plist"
  local TMP
  TMP="$(mktemp)"

  if [ ! -f "$SRC" ]; then
    echo "Template not found: $SRC" >&2
    exit 1
  fi

  sed -e "s|__USER__|$WORKER_USER|g" -e "s|__HOME__|$WORKER_HOME|g" "$SRC" > "$TMP"

  if ! plutil -lint "$TMP" >/dev/null; then
    echo "Rendered plist failed plutil -lint: $TMP" >&2
    cat "$TMP" >&2
    rm -f "$TMP"
    exit 1
  fi

  if sudo launchctl print "system/$LABEL" >/dev/null 2>&1; then
    echo "Unloading existing system/$LABEL"
    sudo launchctl bootout "system/$LABEL" || true
  fi

  sudo install -o root -g wheel -m 644 "$TMP" "$DEST"
  rm -f "$TMP"
  echo "Wrote $DEST (root:wheel 644)"

  echo "Loading system/$LABEL"
  sudo launchctl bootstrap system "$DEST"
  sudo launchctl enable "system/$LABEL"
}

install_daemon com.localai.developer
install_daemon com.localai.reviewer

echo
echo "Installed. Status:"
sudo launchctl print "system/com.localai.developer" | head -10 || true
echo "---"
sudo launchctl print "system/com.localai.reviewer"  | head -10 || true
echo
echo "Logs:"
echo "  $HOME/ai/logs/{developer,reviewer}-launchd.{out,err}"
echo "  $HOME/ai/logs/{developer,reviewer}.log  (from the launcher scripts)"
echo
echo "To uninstall both:"
echo "  sudo launchctl bootout system/com.localai.developer && sudo rm '$DAEMON_DIR/com.localai.developer.plist'"
echo "  sudo launchctl bootout system/com.localai.reviewer  && sudo rm '$DAEMON_DIR/com.localai.reviewer.plist'"
```

Verify (DO NOT execute the script — only syntax-check):
```bash
bash -n scripts/install-launchd-machine2.sh
```

Commit:
```
Switch Machine 2 installer to LaunchDaemons (sudo, system domain, root:wheel)
```

### Task F — Update `docs/OPERATIONS.md`

Read `docs/OPERATIONS.md`. Insert a new subsection between the "Morning startup" and "Endpoint smoke test" sections. The new subsection content is:

```markdown
## Reboot behavior / launchd ownership

Both machines run their workers under launchd, but the two domains differ:

- **Machine 1: LaunchAgent** in `~/Library/LaunchAgents/com.localai.orchestrator.plist`. Loads in the `gui/$UID/` domain when the user logs in to the console. After a reboot, log in normally and the orchestrator starts. Crash-restart is automatic, throttled to one attempt per 60 seconds.
- **Machine 2: LaunchDaemons** in `/Library/LaunchDaemons/com.localai.{developer,reviewer}.plist`, root:wheel. Load in the `system/` domain at boot, before any user logs in — required because Machine 2 is headless and FileVault-encrypted. The daemons run as `admin` via `UserName=admin`. FileVault still asks for the disk password at cold boot; once unlocked, the daemons load without a login. Use `sudo fdesetup authrestart` from M1 for planned remote reboots that auto-unlock the disk.

Check status:

```bash
# Machine 1:
launchctl print "gui/$(id -u)/com.localai.orchestrator" | grep -E 'state|pid|last exit'

# Machine 2 (sudo required to read system daemons):
ssh admin@10.10.10.2 'sudo launchctl print system/com.localai.developer | grep -E "state|pid|last exit"'
ssh admin@10.10.10.2 'sudo launchctl print system/com.localai.reviewer  | grep -E "state|pid|last exit"'
```

Stop launchd from auto-restarting a worker (e.g. for maintenance):

```bash
# Machine 1:
launchctl bootout "gui/$(id -u)/com.localai.orchestrator"
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.localai.orchestrator.plist  # re-enable

# Machine 2 (sudo + system domain):
ssh -t admin@10.10.10.2 'sudo launchctl bootout system/com.localai.developer'
ssh -t admin@10.10.10.2 'sudo launchctl bootstrap system /Library/LaunchDaemons/com.localai.developer.plist'
```

The manual-mode scripts (`scripts/start-*`, `scripts/stop-*`) are now fallbacks for when launchd has been intentionally booted out (e.g. during `/fix-stack` remediation). Running them while launchd-supervised processes are alive will hit the port-collision check and fail safely.

Logs:
- launchd stdout/stderr: `~/ai/logs/*-launchd.{out,err}`
- worker logs: `~/ai/logs/{orchestrator,developer,reviewer}.log`
```

Also update the existing "Morning startup" section: change the manual `scripts/start-*` instructions to note they are a fallback path; the canonical startup is automatic via launchd after login (M1) / boot (M2).

Verify:
```bash
grep -n 'Reboot behavior' docs/OPERATIONS.md
```
Expected: one match.

Commit:
```
Document launchd ownership, reboot behavior, and crash-restart
```

## Acceptance criteria
- All six commits land on the feature branch in order (A → F).
- `git status` is clean at the end.
- `bash -n` and `plutil -lint` pass on every script/plist touched.
- No live-system commands were run (no `launchctl`, no `sudo`, no `ssh`, no `kill`, no `git push`, no `gh`).
- The deleted `configs/launchd/com.localai.workers.plist.template` does not exist in the working tree.

## Test plan
Per-task verification commands are listed inside each task above. No
integration tests run here (those happen in the parent plan's Tasks 7–9
which are out of scope for this sub-plan).

## Rollback plan
The work is on its own feature branch in a worktree. If the frontier
reviewer rejects, simply discard the worktree — no main-branch impact.

## Documentation updates
`docs/OPERATIONS.md` updated in Task F. HTML guide and audit/fix-stack
skill updates are deferred follow-ups (not in this sub-plan).

## Risks and edge cases
- The local agent may try to run install or launchctl commands — the warning at the top of this file is the only guard. If the agent does anything live, the frontier reviewer will see it in the worktree diff and reject.
- `git rm` on `com.localai.workers.plist.template` requires the file to be tracked; if it's already deleted in the worktree base, use `rm -f` instead and let the next commit pick it up.
