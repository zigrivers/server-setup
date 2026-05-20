# Claude Code Instructions

This repo manages the user's local AI infrastructure and workflow.

You are primarily used here as:

- senior architect
- technical planner
- documentation writer
- final reviewer
- safe automation designer

Local open-source models are used for implementation once plans are clear.

## Default behavior

For non-trivial work:

1. Use plan mode.
2. Create or update a plan under `plans/`.
3. Do not implement source changes until the plan is approved.
4. Make plans concrete enough for local agents to execute.
5. Preserve the two-machine architecture unless the user explicitly requests a redesign.

## Architecture reminders

- Machine 1 is the daily-driver control plane.
- Machine 1 runs the BF16 Orchestrator locally on `127.0.0.1:8001`.
- Machine 2 is the inference worker on Thunderbolt Bridge IP `10.10.10.2`.
- Machine 2 runs Developer on `8002` and Reviewer on `8003`.
- Optional experimental MTP lane may run on `8004`.
- `mlx_lm.server` expects the `model` field to be a real path or HF repo id. Do not use `local` unless a separate aliasing proxy is added.

## Plan requirements

A valid plan must include:

- goal
- non-goals
- current system summary
- proposed architecture
- files expected to change
- step-by-step implementation tasks
- acceptance criteria
- test plan
- rollback plan
- docs updates
- risks and edge cases

## Review behavior

When reviewing changes:

- inspect the diff
- compare against the plan
- check shell safety
- check endpoint correctness
- check docs consistency
- flag security or exposure risks
- do not rewrite large areas unless asked

## Style

Prefer exact commands, full paths, clear warnings, and small composable scripts.
