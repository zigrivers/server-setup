---
name: local-review
description: Get a second-opinion review of the current git diff from the local AI stack. Use when the user asks for a local review or a local model's opinion on their changes.
argument-hint: [optional file, area, or diff description]
allowed-tools: Read, Grep, Glob, Bash(git diff), Bash(git status), mcp__local-ai-delegate__local_review, mcp__local-ai-delegate__git_local_summary, mcp__local-ai-delegate__local_ai_status
---

Use the local AI stack as a second-opinion reviewer.

Process:

1. Identify the relevant workspace (absolute path).
2. Inspect git status and git diff yourself first.
3. Call `mcp__local-ai-delegate__local_review` with that workspace.
   - scope: `uncommitted` by default; `staged` for staged changes only; `since-main` when reviewing a branch.
   - If the user gave a focus area in $ARGUMENTS, pass it as `instructions`.
   - If the tool errors, check `mcp__local-ai-delegate__local_ai_status` and report.
4. Present the local model's findings verbatim, attributed to the model named in the
   tool's `Reviewer:` footer. By default that is the Orchestrator on Machine 1, so the
   review works even when Machine 2 is down.
5. Add your own frontier-level judgment:
   - what you agree with
   - what you disagree with
   - what was missed
   - whether this is safe to merge

Target: $ARGUMENTS
