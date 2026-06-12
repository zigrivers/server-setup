# Plan: Survive reboot and auto-restart on crash

## Goal
Make the local AI stack come up automatically after reboot on both machines and self-heal when any worker crashes. After this lands, no manual intervention should be required to get to a healthy `:8001 / :8002 / :8003` after a power cycle or a `kill -9` of any one mlx_lm.server.

## Non-goals
- No changes to model choices, ports, hosts, or the Thunderbolt Bridge config.
- No move away from launchd (no nssm/pm2/systemd-style supervisor).
- No changes to the experimental MTP lane (`:8004`).
- No changes to MCP registration, Claude/Codex skills, or `audit-stack` / `fix-stack`.
- No changes to the HTML canonical guide in this plan — flagged as a follow-up so it can be reviewed separately.

## Current system summary
- **Machine 1 orchestrator** (`mlx_lm.server` on `127.0.0.1:8001`) is currently running as PID 12233, started **manually** Saturday 4 AM. A launchd agent `com.localai.orchestrator` *is* installed at `~/Library/LaunchAgents/com.localai.orchestrator.plist`, but it is the **pre-fix version** (single `ProgramArgument`, no `/bin/bash` wrapper) — `launchctl print` shows `runs = 4`, `last exit code = 1`, `state = not running`. Commit `4051187` updated the template to wrap with `/bin/bash`, but the installer was never re-run.
- **Machine 2 workers** respond healthy on `10.10.10.2:8002` and `:8003`. Launchd state on Machine 2 has not been verified from this session.
- Both `scripts/start-orchestrator.sh` and `scripts/start-worker-models.sh` end with `nohup mlx_lm.server ... &`. This means the process launchd actually tracks is `bash` running the wrapper script, which then forks the real worker and exits cleanly. **With KeepAlive on, launchd would see exit 0 and consider the agent "done" — it would not notice when the real mlx_lm.server crashes.** This is the central reason crash-restart does not currently work even if you flipped `KeepAlive` to `true`.
- Both plist templates currently use `KeepAlive=false` (start once, never resurrect) and `RunAtLoad=true` (fire at user login).
- Machine 2's single combined plist (`com.localai.workers`) runs both Developer and Reviewer via one wrapper. Even with the `exec` fix below, one plist can only `exec` one process, so the workers will be split into **two separate launchd agents**.

## Proposed architecture
Four coordinated changes:

1. **`exec` instead of `nohup ... &` in the launcher scripts** so launchd tracks the real worker PID. The launcher does its venv/env/port-check setup, then `exec mlx_lm.server ...` — the script process is replaced by the worker, giving launchd a long-lived PID to watch and a real exit code when it dies.
2. **Machine 1 orchestrator stays a LaunchAgent** in `~/Library/LaunchAgents/` (loads at user login). Machine 1 is the daily-driver, so first-login-after-reboot triggers the agent — acceptable.
3. **Machine 2 workers become LaunchDaemons** in `/Library/LaunchDaemons/`, owned by `root:wheel`. Daemons load at boot regardless of console login — this is the only way to survive a reboot on a FileVault-encrypted headless Mac without auto-login. Each plist runs as the `admin` user via `UserName=admin`. The old combined `com.localai.workers` LaunchAgent is removed.
4. **Switch `KeepAlive` from `false` to a dict variant** (`SuccessfulExit=false`, `Crashed=true`) with `ThrottleInterval=60`. This restarts the worker on crash or non-zero exit, but throttles so a bad config can't crash-loop and chew CPU. `RunAtLoad=true` stays so workers come up at boot/login.

Manual-mode scripts (`start-orchestrator.sh`, `start-worker-models.sh`, `stop-worker-models.sh`) remain available for ad-hoc use and as a `fix-stack` fallback. The combined `start-worker-models.sh` becomes a thin wrapper that just calls the two per-worker scripts (and warns that launchd should normally own them).

### Why M1=LaunchAgent and M2=LaunchDaemon?
| | M1 (daily driver) | M2 (headless worker) |
|---|---|---|
| FileVault | On | On |
| Console login post-reboot | Yes (user is here) | No (no one types the password) |
| Best fit | LaunchAgent in `gui/$UID/` — loads at login | LaunchDaemon in `system/` — loads at boot |
| Requires sudo to install | No | Yes |

If you ever want M1 to also survive a reboot before login (e.g. you reboot remotely and don't immediately log in), promote M1 to a LaunchDaemon too — same template, different home/user. Out of scope here.

## Files expected to change

**Machine 1**
- Modify: `scripts/start-orchestrator.sh` — replace `nohup ... &` tail with `exec ...`.
- Modify: `configs/launchd/com.localai.orchestrator.plist.template` — `KeepAlive` becomes a dict; add `ThrottleInterval=60` and `ProcessType=Interactive`.
- Modify: `scripts/install-launchd-machine1.sh` — add `chmod 644 "$DEST"` after the `sed`.

**Machine 2** (LaunchDaemons; installer needs sudo)
- Create: `scripts/start-developer.sh` — single-worker launcher (exec).
- Create: `scripts/start-reviewer.sh` — single-worker launcher (exec).
- Modify: `scripts/start-worker-models.sh` — becomes a thin wrapper that invokes the two per-worker scripts in the background (manual-mode only).
- Modify: `scripts/stop-worker-models.sh` — kills both worker PIDs by port, unchanged behavior expected (verify file content during the task).
- Create: `configs/launchd/com.localai.developer.plist.template` (LaunchDaemon — root-owned, system domain, `UserName=admin`).
- Create: `configs/launchd/com.localai.reviewer.plist.template` (same shape).
- Delete: `configs/launchd/com.localai.workers.plist.template` (the obsolete LaunchAgent template).
- Modify: `scripts/install-launchd-machine2.sh` — installs both daemons into `/Library/LaunchDaemons/` with `sudo`, boots out the obsolete `com.localai.workers` LaunchAgent (in `gui/$UID/` AND `user/$UID/`) and removes `~/Library/LaunchAgents/com.localai.workers.plist` if present.

**Docs**
- Modify: `docs/OPERATIONS.md` — add a "Reboot behavior / launchd ownership" subsection explaining that workers are now owned by launchd, with crash-restart and how to check status / view logs / disable.
- Modify: `README.md` (only if it currently describes the manual morning-startup flow — verify during the docs task).

Out of scope but flagged for follow-up: `docs/html/` canonical guide and any audit-stack/fix-stack rules that reference `com.localai.workers` by label.

## Step-by-step implementation tasks

### Task 1: Pre-flight — verified

SSH target `admin@10.10.10.2` is reachable. Machine 2 state captured **2026-05-21**:

- FileVault: **On**
- Auto-login: **NOT SET** (and incompatible with FileVault — drives the M2 = LaunchDaemon decision)
- `com.localai.workers` LaunchAgent: installed at `~/Library/LaunchAgents/com.localai.workers.plist`, currently `state = not running` (same `/bin/bash` wrapper bug as M1).
- Endpoints `:8002` and `:8003` both healthy (workers started manually).
- `~/ai/local-ai-stack` on M2 is a real directory at `/Users/admin/ai/local-ai-stack` (not a symlink).
- M2 repo HEAD: `66e3941` — three commits behind M1's `main`. Task 8 must `git pull` on M2 before running the new installer.

### Task 2: Convert `start-orchestrator.sh` to `exec`

File: `scripts/start-orchestrator.sh`

Replace the trailing block:

```bash
nohup mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  > "$HOME/ai/logs/orchestrator.log" 2>&1 &

echo "Started. Log: $HOME/ai/logs/orchestrator.log"
```

with:

```bash
echo "Log: $HOME/ai/logs/orchestrator.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  >> "$HOME/ai/logs/orchestrator.log" 2>&1
```

Notes for the implementer:
- `exec` replaces the bash process with `mlx_lm.server`, so launchd will track the worker PID directly. There is no `&` and no `nohup` because launchd is the supervisor now.
- Use `>>` (append) rather than `>` (truncate) so log history isn't lost on restart.
- The "Started." line is removed because it would never print — `exec` doesn't return.

Verification:

```bash
bash -n scripts/start-orchestrator.sh   # syntax check, expect no output
```

Commit:

```bash
git add scripts/start-orchestrator.sh
git commit -m "Use exec in start-orchestrator.sh so launchd tracks the real worker PID"
```

### Task 3: Update the orchestrator plist template for crash-restart

File: `configs/launchd/com.localai.orchestrator.plist.template`

Replace:

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

Notes:
- `SuccessfulExit=false` means "restart unless the process exits 0." Combined with `Crashed=true`, any abnormal termination triggers a restart; a clean stop via `launchctl bootout` does not.
- `ThrottleInterval=60` caps restart frequency to one attempt every 60 seconds. We use 60 (not 30) because the BF16 orchestrator model can take 30–60 s to load — if a run dies during load it might have lived for <30 s, and `ThrottleInterval` is measured from *launch time*, so a shorter interval risks slow recovery on transient failures. 60 s leaves the worker headroom to actually start listening before being declared dead-and-throttled on the next iteration.
- `ProcessType=Interactive` keeps the worker at a normal scheduling priority rather than the default background QoS, which is right for a foreground inference server.

Also update `scripts/install-launchd-machine1.sh` to chmod the rendered plist. After the `sed "s|__HOME__|$HOME|g" "$SRC" > "$DEST"` line, insert:

```bash
chmod 644 "$DEST"
```

This is belt-and-braces — `launchctl bootstrap` on macOS 13+ is stricter about plist file permissions than older versions.

Verification:

```bash
plutil -lint configs/launchd/com.localai.orchestrator.plist.template
bash -n scripts/install-launchd-machine1.sh
```
Expected: `... OK` and no output.

Commit:

```bash
git add configs/launchd/com.localai.orchestrator.plist.template scripts/install-launchd-machine1.sh
git commit -m "Enable crash-restart for orchestrator launchd agent (KeepAlive dict, ThrottleInterval 60, chmod 644)"
```

### Task 4: Create per-worker launcher scripts for Machine 2

File: `scripts/start-developer.sh` (new, mode 755):

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

File: `scripts/start-reviewer.sh` (new, mode 755):

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
PORT="${REVIEW_PORT:-8003}"
MODEL="${REVIEW_MODEL_PATH:-$HOME/ai/models/reviewer-qwen36-27b-heretic-bf16}"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already listening on port $PORT:"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN
  exit 1
fi

echo "Starting Reviewer on $HOST:$PORT (model: $MODEL)"
echo "Log: $HOME/ai/logs/reviewer.log"
exec mlx_lm.server \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  >> "$HOME/ai/logs/reviewer.log" 2>&1
```

Then make `scripts/start-worker-models.sh` a thin manual-mode wrapper. Read its current content first, then replace the body (keeping `set -euo pipefail`) with:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Manual-mode launcher. Normally launchd owns these via
#   com.localai.developer and com.localai.reviewer.
# Use this script only when you've intentionally booted the launchd
# agents out (e.g. during debugging).

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
"$REPO_DIR/scripts/start-developer.sh" &
DEV_PID=$!
"$REPO_DIR/scripts/start-reviewer.sh" &
REV_PID=$!

echo "Developer  pid=$DEV_PID  log=$HOME/ai/logs/developer.log"
echo "Reviewer   pid=$REV_PID  log=$HOME/ai/logs/reviewer.log"
echo "Note: these run in the background; launchd is not supervising them."
```

Verification:

```bash
chmod +x scripts/start-developer.sh scripts/start-reviewer.sh
bash -n scripts/start-developer.sh
bash -n scripts/start-reviewer.sh
bash -n scripts/start-worker-models.sh
```
Expected: no output from any of the three.

Commit:

```bash
git add scripts/start-developer.sh scripts/start-reviewer.sh scripts/start-worker-models.sh
git commit -m "Split Machine 2 workers into per-worker exec launchers"
```

### Task 5: Create per-worker LaunchDaemon templates and remove the combined LaunchAgent

These plists install into `/Library/LaunchDaemons/` (root-owned). Because daemons don't inherit a user session's environment, the template explicitly sets `UserName`, `WorkingDirectory`, `HOME`, and `PATH` so the launcher script can find the venv, the model files, and `mlx_lm.server`. The substitution token `__USER__` is replaced with `admin` (Machine 2's worker user) at install time; `__HOME__` with `/Users/admin`.

File: `configs/launchd/com.localai.developer.plist.template` (new):

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

File: `configs/launchd/com.localai.reviewer.plist.template` (new):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- LaunchDaemon template. See the developer template for the
     substitution / install / load semantics. -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.localai.reviewer</string>
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
    <string>__HOME__/ai/local-ai-stack/scripts/start-reviewer.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
    <key>Crashed</key><true/>
  </dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>__HOME__/ai/logs/reviewer-launchd.out</string>
  <key>StandardErrorPath</key><string>__HOME__/ai/logs/reviewer-launchd.err</string>
</dict>
</plist>
```

Delete the obsolete combined LaunchAgent template:

```bash
git rm configs/launchd/com.localai.workers.plist.template
```

Verification:

```bash
plutil -lint configs/launchd/com.localai.developer.plist.template
plutil -lint configs/launchd/com.localai.reviewer.plist.template
```
Expected: both report `... OK`.

Commit:

```bash
git add configs/launchd/com.localai.developer.plist.template \
        configs/launchd/com.localai.reviewer.plist.template \
        configs/launchd/com.localai.workers.plist.template
git commit -m "Replace combined workers LaunchAgent with per-worker LaunchDaemon templates"
```

### Task 6: Rewrite the Machine 2 installer for LaunchDaemons

The new installer:
1. Boots out and removes the obsolete `com.localai.workers` **LaunchAgent** (in `gui/$UID/` AND `user/$UID/`) from `~/Library/LaunchAgents/`.
2. Renders both LaunchDaemon plists into a temp file with `__USER__` / `__HOME__` substituted.
3. Copies them into `/Library/LaunchDaemons/` with `sudo install` (sets `root:wheel`, mode 644 in one step).
4. Boots them into the `system/` domain with `sudo launchctl bootstrap system`.

File: `scripts/install-launchd-machine2.sh`

Replace the whole script body (keep the shebang and `set -euo pipefail`) with:

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
# This script will prompt for sudo password once and reuse the cached creds.
echo "Installing LaunchDaemons (sudo required)..."
sudo -v

install_daemon() {
  local LABEL="$1"
  local SRC="$REPO_DIR/configs/launchd/${LABEL}.plist.template"
  local DEST="$DAEMON_DIR/${LABEL}.plist"
  local TMP="$(mktemp)"

  if [ ! -f "$SRC" ]; then
    echo "Template not found: $SRC" >&2
    exit 1
  fi

  # Render template with __USER__ and __HOME__ substituted.
  sed -e "s|__USER__|$WORKER_USER|g" -e "s|__HOME__|$WORKER_HOME|g" "$SRC" > "$TMP"

  # Validate before installing.
  if ! plutil -lint "$TMP" >/dev/null; then
    echo "Rendered plist failed plutil -lint: $TMP" >&2
    cat "$TMP" >&2
    rm -f "$TMP"
    exit 1
  fi

  # Bootout any existing daemon with this label.
  if sudo launchctl print "system/$LABEL" >/dev/null 2>&1; then
    echo "Unloading existing system/$LABEL"
    sudo launchctl bootout "system/$LABEL" || true
  fi

  # Install: sudo install -o root -g wheel -m 644 sets ownership and perms atomically.
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

Verification:

```bash
bash -n scripts/install-launchd-machine2.sh
```
Expected: no output.

Commit:

```bash
git add scripts/install-launchd-machine2.sh
git commit -m "Switch Machine 2 installer to LaunchDaemons (sudo, system domain, root:wheel)"
```

### Task 7: Deploy on Machine 1

This task touches a running system. Run from Machine 1 (this Mac).

1. Stop the manually-started orchestrator so launchd can bind `:8001`:
   ```bash
   cd /Users/kenallred/Developer/server-setup
   scripts/stop-orchestrator.sh
   sleep 2
   ! curl -s -m 2 http://127.0.0.1:8001/health >/dev/null && echo "OK: port free" || echo "FAIL: still listening"
   ```
   Expected: `OK: port free`.

2. (Re)install the fixed plist:
   ```bash
   scripts/install-launchd-machine1.sh
   ```
   Expected: `Wrote .../com.localai.orchestrator.plist`, `Loading com.localai.orchestrator`, and a `launchctl print` excerpt with no error.

3. Wait up to 60 s for the model to load, then health-check:
   ```bash
   for i in 1 2 3 4 5 6; do
     sleep 10
     if curl -s -m 2 http://127.0.0.1:8001/health >/dev/null; then
       echo "OK after ${i}0s"; break
     fi
   done
   curl -s http://127.0.0.1:8001/health
   ```
   Expected: `{"status": "ok"}`.

4. Confirm launchd actually owns the running process:
   ```bash
   launchctl print "gui/$(id -u)/com.localai.orchestrator" | grep -E 'state|pid|last exit'
   ```
   Expected: `state = running` and a numeric `pid`.

No commit — this is a deploy step.

### Task 8: Deploy on Machine 2

Run these commands from Machine 1 over SSH. The installer prompts for `sudo` once interactively — `ssh -t` is therefore required so a TTY exists.

1. Sync the repo to Machine 2:
   ```bash
   ssh admin@10.10.10.2 'cd ~/ai/local-ai-stack && git pull --ff-only && git log --oneline -1'
   ```
   Expected: HEAD matches the commits from Tasks 2–6.

2. Stop the manually-running workers so launchd can bind `:8002` and `:8003`:
   ```bash
   ssh admin@10.10.10.2 'cd ~/ai/local-ai-stack && scripts/stop-worker-models.sh || true'
   ssh admin@10.10.10.2 'sleep 2; lsof -nP -iTCP:8002 -sTCP:LISTEN; lsof -nP -iTCP:8003 -sTCP:LISTEN'
   ```
   Expected: no output from `lsof` (ports free).

3. Install both LaunchDaemons (TTY needed for the `sudo` prompt):
   ```bash
   ssh -t admin@10.10.10.2 'cd ~/ai/local-ai-stack && scripts/install-launchd-machine2.sh'
   ```
   Expected: lines indicating `com.localai.workers` was booted out and removed, both daemons written to `/Library/LaunchDaemons/` as root:wheel 644, and both bootstrapped into the `system/` domain. The sudo password prompt should fire exactly once.

4. Wait up to 90 s and health-check both:
   ```bash
   for i in 1 2 3 4 5 6 7 8 9; do
     sleep 10
     D=$(curl -s -m 2 http://10.10.10.2:8002/health || true)
     R=$(curl -s -m 2 http://10.10.10.2:8003/health || true)
     [ -n "$D" ] && [ -n "$R" ] && echo "OK after ${i}0s" && break
   done
   curl -s http://10.10.10.2:8002/health; echo
   curl -s http://10.10.10.2:8003/health
   ```
   Expected: both return `{"status": "ok"}`.

5. Confirm launchd owns both processes (note: `sudo` is required to print `system/` daemons):
   ```bash
   ssh admin@10.10.10.2 'sudo launchctl print "system/com.localai.developer" | grep -E "state|pid"'
   ssh admin@10.10.10.2 'sudo launchctl print "system/com.localai.reviewer"  | grep -E "state|pid"'
   ```
   Expected: `state = running` and a numeric `pid` for each.

No commit — deploy step.

### Task 9: Verify crash-restart actually works

This is the real acceptance test for `KeepAlive`. Done after deploy.

Each test must assert **two** conditions before declaring success: (a) a new PID exists and differs from the killed one, and (b) the endpoint returns `{"status": "ok"}` in the same iteration. Checking only the PID can pass on a transient process that immediately re-died.

1. **Orchestrator (Machine 1):**
   ```bash
   OLD_PID=$(launchctl print "gui/$(id -u)/com.localai.orchestrator" | awk '/^[[:space:]]*pid =/ {print $3}')
   echo "Before: $OLD_PID"
   kill -9 "$OLD_PID"

   OK=0
   for i in 1 2 3 4 5 6 8 10 12 14; do
     sleep 10
     NEW_PID=$(launchctl print "gui/$(id -u)/com.localai.orchestrator" 2>/dev/null | awk '/^[[:space:]]*pid =/ {print $3}')
     if [ -n "$NEW_PID" ] && [ "$NEW_PID" != "$OLD_PID" ] \
        && curl -sf -m 2 http://127.0.0.1:8001/health >/dev/null; then
       echo "Restarted as $NEW_PID and healthy after ${i}0s"
       OK=1; break
     fi
   done
   [ "$OK" = 1 ] || { echo "FAIL: orchestrator did not recover"; exit 1; }
   ```
   Expected: success line within ~140 s. The throttle (60 s) plus a cold model load (~30–60 s) dominate the wait; the loop covers 140 s of real time.

2. **Developer (Machine 2):** Use `ssh -t admin@10.10.10.2 sudo bash -s <<'EOF'` so the entire test block runs on Machine 2 as root in a single shell (needed for `launchctl print system/...` and to send the signal to the daemon's child process). The `-t` allocates a TTY for the sudo prompt.
   ```bash
   ssh -t admin@10.10.10.2 sudo bash -s <<'EOF'
   set -u
   LABEL=com.localai.developer
   PORT=8002
   OLD_PID=$(launchctl print "system/$LABEL" | awk '/^[[:space:]]*pid =/ {print $3}')
   echo "Before: $OLD_PID"
   kill -9 "$OLD_PID"

   OK=0
   for i in 1 2 3 4 5 6 8 10 12 14; do
     sleep 10
     NEW_PID=$(launchctl print "system/$LABEL" 2>/dev/null | awk '/^[[:space:]]*pid =/ {print $3}')
     if [ -n "$NEW_PID" ] && [ "$NEW_PID" != "$OLD_PID" ] \
        && curl -sf -m 2 "http://10.10.10.2:$PORT/health" >/dev/null; then
       echo "Restarted as $NEW_PID and healthy after ${i}0s"
       OK=1; break
     fi
   done
   [ "$OK" = 1 ] || { echo "FAIL: developer did not recover"; exit 1; }
   EOF
   ```

3. **Reviewer (Machine 2):** Same as step 2, with `LABEL=com.localai.reviewer` and `PORT=8003`.

If any of these don't recover, do NOT declare success. Inspect `~/ai/logs/<worker>-launchd.err` first. Most-likely causes:
- `ThrottleInterval` colliding with a particularly slow first model load → raise `ThrottleInterval` to 90 and retest.
- Daemon failed to find `mlx_lm.server` because `EnvironmentVariables.PATH` is wrong → add the venv path to the daemon plist's `EnvironmentVariables.PATH`, or let `source .venv/bin/activate` handle it (current default).
- Plist file mode/ownership wrong → `launchctl bootstrap system` rejected it (must be `root:wheel 644`; see Task 6's `sudo install -o root -g wheel -m 644`).

### Task 10: Update OPERATIONS.md

File: `docs/OPERATIONS.md`

Add a new subsection between "Morning startup" and "Endpoint smoke test":

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

Also update the "Morning startup" section to note that the manual
`scripts/start-*` commands are now a fallback for when launchd has been
intentionally booted out, not the normal path.

Verification:

```bash
grep -n 'Reboot behavior' docs/OPERATIONS.md
```
Expected: one match.

Commit:

```bash
git add docs/OPERATIONS.md
git commit -m "Document launchd ownership, reboot behavior, and crash-restart"
```

## Acceptance criteria
- `launchctl print gui/$(id -u)/com.localai.orchestrator` on Machine 1 reports `state = running` with a real PID.
- `sudo launchctl print system/com.localai.developer` and `system/com.localai.reviewer` on Machine 2 both report `state = running` with real PIDs running as `admin`.
- `/Library/LaunchDaemons/com.localai.developer.plist` and `.../com.localai.reviewer.plist` on Machine 2 are present, `root:wheel`, mode `0644`.
- The obsolete `~/Library/LaunchAgents/com.localai.workers.plist` does NOT exist on Machine 2, and `launchctl print gui/$(id -u)/com.localai.workers` returns "Could not find service."
- Killing any single worker with `kill -9` produces a new PID AND a passing `/health` response in the same loop iteration within ~140 seconds (Task 9).
- After a full reboot of Machine 2 (still FileVault-encrypted, no auto-login), both `:8002` and `:8003` return `{"status": "ok"}` without any manual intervention beyond FileVault's normal cold-boot password prompt at the M2 console (or remote unlock — `sudo fdesetup authrestart` from M1 if you want a one-shot FV-unlocked reboot).
- After a reboot of Machine 1 followed by the user logging in, `:8001` returns `{"status": "ok"}` automatically.
- `git status` is clean; new files (`start-developer.sh`, `start-reviewer.sh`, two new LaunchDaemon templates) are committed; `com.localai.workers.plist.template` is deleted.

## Test plan

Automated checks performed during Tasks 7–9 above (deploy + crash test) cover the bulk of acceptance.

Additionally, a one-time **manual reboot test** is required to fully validate reboot survival:

1. **Machine 1 reboot:** `sudo reboot`. At the FileVault prompt, log in normally. After login, wait 140 s (covers throttle + cold model load), then:
   ```bash
   curl -s http://127.0.0.1:8001/health
   launchctl print "gui/$(id -u)/com.localai.orchestrator" | grep -E 'state|pid'
   ```
   Expected: orchestrator state is `running` with a real PID; health check returns ok.

2. **Machine 2 reboot (the critical one):** For an FV-unlocked one-shot reboot, from Machine 1:
   ```bash
   ssh -t admin@10.10.10.2 'sudo fdesetup authrestart'
   ```
   This prompts for the M2 FileVault password once, then reboots and unlocks the disk automatically — proving the LaunchDaemon path works on a real reboot without anyone touching the M2 console.

   Wait ~60 s for boot, then another 140 s for daemons to load and models to come up. Verify:
   ```bash
   curl -s http://10.10.10.2:8002/health; echo
   curl -s http://10.10.10.2:8003/health; echo
   ssh admin@10.10.10.2 'sudo launchctl print system/com.localai.developer | grep -E "state|pid"'
   ssh admin@10.10.10.2 'sudo launchctl print system/com.localai.reviewer  | grep -E "state|pid"'
   ```
   Expected: both endpoints return ok; both daemons report `state = running` with PIDs running as `admin`.

3. **Cold-boot test (optional but recommended):** Power-cycle Machine 2. After it comes back up to the FileVault prompt, *don't* log in — just enter the FV password and then close the lid / leave it. After 200 s, verify endpoints from M1. This proves the daemons run at boot without any console session.

If a test fails, diagnose in this order:
1. SSH into the affected machine and check `sudo launchctl print system/com.localai.<label>` (M2) or `launchctl print gui/$(id -u)/com.localai.orchestrator` (M1). "Could not find service" means the plist isn't installed or didn't load.
2. Inspect `~/ai/logs/<worker>-launchd.err` on the affected machine for spawn errors.
3. Inspect `~/ai/logs/<worker>.log` for application-level errors (model file missing, OOM, etc.).

## Rollback plan

Per-task rollback (after Tasks 2–6 commits):

```bash
git revert <commit-sha>           # or git reset --hard HEAD~N if not pushed
```

Deploy rollback on Machine 1:

```bash
launchctl bootout "gui/$(id -u)/com.localai.orchestrator"
rm ~/Library/LaunchAgents/com.localai.orchestrator.plist
# go back to manual start:
cd ~/ai/local-ai-stack && scripts/start-orchestrator.sh
```

Deploy rollback on Machine 2 (LaunchDaemons live in `/Library/LaunchDaemons/` — needs sudo):

```bash
ssh -t admin@10.10.10.2 'sudo launchctl bootout system/com.localai.developer; sudo launchctl bootout system/com.localai.reviewer; sudo rm -f /Library/LaunchDaemons/com.localai.developer.plist /Library/LaunchDaemons/com.localai.reviewer.plist'
ssh admin@10.10.10.2 'cd ~/ai/local-ai-stack && scripts/start-worker-models.sh'
```

If the `KeepAlive` dict misbehaves (e.g. restart loops on a slow model load), the minimal hotfix is to edit the installed plist in place and set `KeepAlive` back to `<false/>`, then `launchctl bootout` + `launchctl bootstrap` the agent. This buys time without reverting source.

## Documentation updates
- `docs/OPERATIONS.md` — new "Reboot behavior / launchd ownership" subsection (Task 10) and an updated "Morning startup" note.
- Follow-up (not in this plan): `docs/html/` canonical guide may reference `com.localai.workers` by label or describe the morning-startup ritual; flag during the next `/audit-stack` run.
- Follow-up (not in this plan): `.claude/commands/fix-stack.md` and `audit-stack` rules — verify they don't pattern-match on the now-removed `com.localai.workers` label.

## Risks and edge cases
- **`gui/` domain requires console login (M1 only).** Machine 1's orchestrator runs as a LaunchAgent in `gui/$UID/` and loads at user login, not at boot. M1 is the daily-driver Mac so this is acceptable — after a reboot the user logs in normally and the agent fires. If you ever need M1 to come up before any login (e.g. remote reboot), promote it to a LaunchDaemon using the same template shape as M2.
- **Machine 2 LaunchDaemon environment.** Daemons don't inherit a user session's env, so the plist explicitly sets `UserName=admin`, `WorkingDirectory=/Users/admin`, `HOME=/Users/admin`, and `PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin`. If the launcher script ever assumes other env vars (e.g. `LANG`, `TMPDIR`), add them to `EnvironmentVariables`. The `.env` file at the repo root continues to provide model-path overrides because the launcher sources it explicitly.
- **Machine 2 daemon → file access.** The daemons run as `admin`, not root, via `UserName=admin`. Files in `/Users/admin/ai/models/` and `/Users/admin/ai/local-ai-stack/.venv/` are owned by `admin` and remain accessible. If you ever move models to a path that isn't `admin`-readable, the daemon will fail to load them.
- **`com.localai.workers` plist removal — old vs new domain.** The obsolete plist was a LaunchAgent in `gui/$UID/`, while the new plists are LaunchDaemons in `system/`. The two coexist on disk in different directories (`~/Library/LaunchAgents/` vs `/Library/LaunchDaemons/`), so port conflict is the only failure mode — Task 8's pre-deploy `stop-worker-models.sh` + `lsof` check handles that.
- **FileVault and reboot.** With FileVault on (current state), unattended cold-boot recovery still requires *someone* to enter the FV password — physically at the M2 console, or via `sudo fdesetup authrestart` from M1 for planned reboots. Once the disk is unlocked, the LaunchDaemons load at boot without any console login. This is the maximum-automation outcome with FV enabled; full unattended power-loss recovery would require disabling FileVault, which is out of scope.
- **`set -euo pipefail` + venv `activate`.** Verified safe: the venv's activate script uses `${PS1-}` and `${VIRTUAL_ENV_DISABLE_PROMPT-}` guards, so `set -u` does not trip on unset `PS1` under launchd's non-interactive shell. A regression here (e.g. a newer virtualenv that drops the guards) would manifest as immediate `exit 1` and a throttle loop; check `~/ai/logs/*-launchd.err` if that happens.
- **Slow model load vs. `ThrottleInterval`.** Cold-loading the orchestrator BF16 model can take 30–60 s. `ThrottleInterval=60` only governs *restart frequency*, not first-launch time, so it is safe at boot. The value is chosen to exceed a typical successful load: a crash that happens *after* the worker starts listening will be retried promptly (the previous run lasted >60 s, so the throttle is already satisfied); a crash *during* load gets the full 60 s breathing room before retry.
- **`lsof` precheck and TIME_WAIT.** The precheck filters with `-sTCP:LISTEN`, which explicitly excludes `TIME_WAIT` sockets — so the kernel holding a port in `TIME_WAIT` after a `kill -9` will not false-trigger the precheck. mlx_lm.server (via uvicorn) sets `SO_REUSEADDR`, so even a lingering `TIME_WAIT` would not block `bind()`. The precheck only triggers when something is actively listening, which is the correct behavior (refuse to start a duplicate). Kept as-is.
- **`exec` semantics.** Because the launcher script `exec`s the worker, the `mkdir -p logs` and `lsof` precheck run *before* the exec. Any failure there exits non-zero and launchd records it. `SuccessfulExit=false` means launchd will treat that as a restart trigger — so a persistently-failing precheck (e.g. model file missing) will throttle-loop forever at one attempt per 60 s. Acceptable; the launchd log surfaces it clearly.
- **`stop-*.sh` no longer fully stops the workers under launchd.** Running `scripts/stop-orchestrator.sh` (or `stop-worker-models.sh`) will kill mlx_lm.server, then launchd will restart it within 60 s. The canonical stop is `launchctl bootout gui/$(id -u)/<label>`. Task 10's docs update calls this out. The legacy stop scripts are kept for the case where launchd has already been booted out (e.g. during fix-stack remediation).
- **Manual-mode confusion.** With launchd owning the workers, running `scripts/start-orchestrator.sh` manually will now fail the port-collision precheck (because launchd already bound the port). This is the right behavior but may surprise users — the doc update in Task 10 calls it out.
- **Log rotation.** Both launcher scripts use `>>` append, so `~/ai/logs/*.log` will grow unbounded. Flagged as a follow-up (`newsyslog.conf` entry or a periodic rotation script). Not blocking.
- **`com.localai.workers` references elsewhere.** Audit/fix-stack skills and the HTML guide may still mention the old label by name. Flagged as a follow-up; not blocking, because the audit will just report drift, not break.
- **SSH target.** Plan uses `admin@10.10.10.2` (the canonical target from `.claude/commands/audit-stack.md`). Confirmed reachable.
- **`local-ai-stack` symlink.** Both plists assume `~/ai/local-ai-stack` points at the repo. Confirmed present on Machine 1 (symlinks to `/Users/kenallred/Developer/server-setup`); Task 1's pre-flight on Machine 2 should also confirm the equivalent symlink exists there before installing.
