---
name: delegate-local
description: Create or validate a plan, then delegate execution to the local multi-agent stack
argument-hint: [task description or plan file]
allowed-tools: Read, Grep, Glob, Bash(git status), Bash(pwd), local-ai-delegate__local_ai_status, local-ai-delegate__run_local_plan, local-ai-delegate__git_local_summary
---

You are the frontier architect and reviewer.

Use this skill to hand off implementation work to the local multi-agent system.

Workflow:

1. Understand the task.
2. If there is not already a concrete plan file, create one under `plans/YYYY-MM-DD-feature-name.md`.
3. The plan must include:
   - Goal
   - Non-goals
   - Current system summary
   - Proposed architecture
   - Files expected to change
   - Step-by-step implementation tasks
   - Acceptance criteria
   - Test plan with exact commands
   - Rollback plan
   - Documentation updates
   - Risks and edge cases
4. Show the plan and ask for approval before execution.
5. After approval, call `local-ai-delegate__run_local_plan` with:
   - `plan_file`
   - `workspace`
   - `in_place=false`
6. Summarize:
   - worktree path
   - branch
   - local reviewer approval status
   - files changed
   - tests run
   - unresolved issues
7. Do final frontier-level review after execution.

Task: $ARGUMENTS
