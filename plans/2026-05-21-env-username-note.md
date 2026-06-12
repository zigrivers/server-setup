# Plan: Add username note to env.machine2.example

## Goal
Make it obvious to anyone setting up Machine 2 that the hardcoded `/Users/admin` paths must be replaced with their actual macOS username.

## Non-goals
- Changing any actual paths or variable values
- Modifying scripts or plist templates
- Making the file dynamic or template-substituted

## Current system summary
`configs/env.machine2.example` has two lines with hardcoded `/Users/admin/` paths:
```
DEV_MODEL_PATH=/Users/admin/ai/models/developer-qwen36-27b-heretic2-mixed94
REVIEW_MODEL_PATH=/Users/admin/ai/models/reviewer-llmfan46-qwen36-27b-heretic-v2-bf16
```
The header comment says "adjust paths as needed" but does not call out the username specifically.

## Proposed architecture
Add a one-line inline comment after the header warning that explicitly calls out the username substitution requirement. No structural changes.

## Files expected to change
- `configs/env.machine2.example`

## Step-by-step implementation tasks
1. Open `configs/env.machine2.example`.
2. Replace the header block:
   ```
   # Machine 2 / inference worker
   # Copy to ~/ai/local-ai-stack/.env and adjust paths as needed.
   ```
   with:
   ```
   # Machine 2 / inference worker
   # Copy to ~/ai/local-ai-stack/.env and adjust paths as needed.
   # NOTE: Replace /Users/admin with your actual macOS username (run: whoami).
   ```
3. No other changes.

## Acceptance criteria
- `configs/env.machine2.example` contains the note about replacing `/Users/admin`
- No other lines are modified
- File still parses correctly as a shell-sourceable env file

## Test plan
```bash
# Verify the note is present
grep -n "whoami" configs/env.machine2.example

# Verify nothing else changed
git diff configs/env.machine2.example
```

## Rollback plan
`git checkout configs/env.machine2.example`

## Documentation updates
None required — this file is its own documentation.

## Risks and edge cases
- None. This is a comment-only change.
