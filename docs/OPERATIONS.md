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

## Shutdown

Machine 1:

```bash
scripts/stop-orchestrator.sh
```

Machine 2:

```bash
scripts/stop-worker-models.sh
```
