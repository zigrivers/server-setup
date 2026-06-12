---
name: local-review
description: Use the local AI stack for a second opinion on the current git diff or project state
argument-hint: [optional file, area, or diff description]
allowed-tools: Read, Grep, Glob, Bash(git diff), Bash(git status), local-ai-delegate__local_review, local-ai-delegate__git_local_summary, local-ai-delegate__local_ai_status
---

Use the local AI stack as a second-opinion reviewer.

Process:

1. Identify the relevant workspace (absolute path).
2. Inspect git status and git diff yourself first.
3. Call `local-ai-delegate__local_review` with that workspace.
   - scope: `uncommitted` by default; `since-main` when reviewing a branch.
   - If the user gave a focus area in $ARGUMENTS, pass it as `instructions`.
   - If the tool errors, check `local-ai-delegate__local_ai_status` and report.
4. Present the local reviewer's findings verbatim (clearly attributed to the
   local Reviewer model).
5. Add your own frontier-level judgment:
   - what you agree with
   - what you disagree with
   - what was missed
   - whether this is safe to merge

Target: $ARGUMENTS
