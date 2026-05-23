---
name: local-review
description: Use the local AI stack for a second opinion on the current git diff or project state
argument-hint: [optional file, area, or diff description]
allowed-tools: Read, Grep, Glob, Bash(git diff), Bash(git status), local-ai-delegate__git_local_summary, local-ai-delegate__local_ai_status
---

Use the local AI stack as a second-opinion reviewer.

Process:

1. Identify the relevant workspace.
2. Inspect git status and git diff.
3. Use `local-ai-delegate__git_local_summary`.
4. Present the local findings.
5. Add your own frontier-level judgment:
   - what you agree with
   - what you disagree with
   - what was missed
   - whether this is safe to merge

Target: $ARGUMENTS
