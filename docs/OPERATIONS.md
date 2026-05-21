# Daily Operations

## Morning startup

On Machine 1:

```bash
cd ~/ai/local-ai-stack
scripts/start-orchestrator.sh
scripts/m1-ai-status.sh
```

On Machine 2:

```bash
cd ~/ai/local-ai-stack
scripts/start-worker-models.sh
scripts/m2-ai-status.sh
```

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

## Shutdown

Machine 1:

```bash
scripts/stop-orchestrator.sh
```

Machine 2:

```bash
scripts/stop-worker-models.sh
```
