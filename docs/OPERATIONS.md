# Daily Operations

## Morning startup

Normally **nothing to do** — launchd brings both machines up automatically
(M1 at login, M2 at boot — see "Reboot behavior / launchd ownership"
below). The manual launchers below are a fallback for when launchd has
been intentionally booted out.

Manual fallback — on Machine 1:

```bash
cd ~/ai/local-ai-stack
scripts/start-orchestrator.sh   # only if launchd has been booted out
scripts/m1-ai-status.sh
```

Manual fallback — on Machine 2:

```bash
cd ~/ai/local-ai-stack
scripts/start-worker-models.sh  # only if launchd has been booted out
scripts/m2-ai-status.sh
```

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

Running `scripts/start-*` while launchd-supervised processes are alive
will hit the port-collision precheck and fail safely. The matching
`scripts/stop-*` won't truly stop a launchd-supervised worker — launchd
will restart it within 60 seconds; use `launchctl bootout` for a real
stop.

Logs:
- launchd stdout/stderr: `~/ai/logs/*-launchd.{out,err}`
- worker logs: `~/ai/logs/{orchestrator,developer,reviewer}.log`

## Endpoint smoke test

From Machine 1:

```bash
scripts/smoke-test-endpoints.sh
```

## Plan → execute workflow

In a project repo:

```bash
mkdir -p plans
```

Ask Claude Code or Codex to create a plan:

```text
Create a plan under plans/YYYY-MM-DD-feature.md. Do not implement yet.
```

After approval:

```bash
local-exec-plan plans/YYYY-MM-DD-feature.md --workspace .
```

Or from Claude Code:

```text
/delegate-local execute plans/YYYY-MM-DD-feature.md in a separate worktree
```

## Review the generated worktree

```bash
git worktree list
cd ../your-repo-local-feature-*
git status
git diff
make test   # or npm test / pytest / cargo test
```

Then ask Claude/Codex for final review.

## Auditing the deployed stack

When you want a holistic check of *both* Macs against the canonical
HTML guide (rather than the basic infra preflight), use the audit
launcher:

```bash
cd ~/ai/local-ai-stack
scripts/audit-stack.sh                    # full audit
scripts/audit-stack.sh "launchd only"     # focused audit
```

The script launches Claude Code with the right `--add-dir` flags
(skipping any directories that don't exist yet) and runs the
`/audit-stack` slash command. Claude inspects Machine 1 directly and
Machine 2 via SSH, then produces a per-machine pass/fail table with
exact remediation commands.

You can also invoke the slash command directly from any Claude Code
session opened in this repo:

```text
/audit-stack
```

When the audit flags fixable items, the companion remediator runs the
safely-idempotent ones for you and surfaces the rest for explicit
approval:

```bash
scripts/fix-stack.sh                    # full remediation
scripts/fix-stack.sh "launchd only"     # focused
```

Or `/fix-stack` from inside a session. Triage rules (auto-safe vs
approve vs long-running vs human-only) are defined in
`.claude/commands/fix-stack.md`. Machine 2 fixes always remain
human-gated.

## Shutdown

Machine 1:

```bash
scripts/stop-orchestrator.sh
```

Machine 2:

```bash
scripts/stop-worker-models.sh
```
