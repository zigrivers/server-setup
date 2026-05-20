# Repository AI Instructions

This repository is the source of truth for the user's local two-Mac AI development stack.

Read these files before substantial work:

- `docs/ARCHITECTURE.md`
- `docs/AI_WORKFLOW.md`
- `docs/SETUP.md`
- `docs/OPERATIONS.md`
- `docs/TROUBLESHOOTING.md`

## Default behavior for Codex

For non-trivial changes:

1. Act as a frontier architect first.
2. Create or update a plan under `plans/`.
3. Do not implement source-code changes until the plan is approved.
4. Prefer small, reviewable commits.
5. When changing scripts, preserve macOS / Apple Silicon assumptions.
6. When changing model endpoints, remember:
   - Machine 1 Orchestrator: `http://127.0.0.1:8001/v1`
   - Machine 2 Developer: `http://10.10.10.2:8002/v1`
   - Machine 2 Reviewer: `http://10.10.10.2:8003/v1`
7. Do not replace full model paths with aliases like `local` or `default` when calling `mlx_lm.server`.

## Planning requirements

Every implementation plan must include:

- Goal
- Non-goals
- Current system summary
- Proposed architecture
- Files expected to change
- Step-by-step tasks
- Acceptance criteria
- Test plan with exact commands
- Rollback plan
- Documentation updates
- Risks and edge cases

## Review requirements

When reviewing local-agent changes:

- Compare the diff against the plan.
- Verify tests were added or updated.
- Check endpoint paths and machine-specific assumptions.
- Check that shell scripts are safe and idempotent.
- Flag any behavior that could expose local servers publicly.
- Do not approve broad destructive tooling.

## Strong preference

Keep this repo boring, explicit, and auditable. It is infrastructure. Cleverness is a liability.
