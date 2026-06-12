# Plan: Commit pending changes and clean up worktree

## Goal
Land two pending changes onto `main` as separate commits and remove the orphaned worktree/branch left by the failed `delegate-local` trial run.

## Non-goals
- Changing any logic beyond what is already modified
- Rebasing or squashing existing history
- Pushing to remote (that happens separately)

## Current system summary
- Main workspace (`/Users/kenallred/Developer/server-setup`) is on `main` with one unstaged change: `src/local_ai_stack/local_agents.py` (removed `from __future__ import annotations`, replaced `List`/`Dict` with `list`/`dict` to fix LangGraph `get_type_hints` compatibility on Python 3.12).
- Worktree at `/Users/kenallred/Developer/server-setup-local-2026-05-21-env-username-note-20260521-054204` (branch `ai/local/2026-05-21-env-username-note-20260521-054204`) has one unstaged change: `configs/env.machine2.example` (adds username NOTE comment).
- Both changes are verified correct and reviewer-approved.

## Proposed architecture
Work in-place on `main`. Steps:
1. Copy `configs/env.machine2.example` from the worktree into the main workspace.
2. Stage and commit `src/local_ai_stack/local_agents.py`.
3. Stage and commit `configs/env.machine2.example`.
4. Remove the worktree and delete the branch.

## Files expected to change
- `src/local_ai_stack/local_agents.py` (committed, no content change)
- `configs/env.machine2.example` (committed, no content change)

## Step-by-step implementation tasks

1. Copy the modified file from the worktree into the main workspace:
   ```bash
   cp /Users/kenallred/Developer/server-setup-local-2026-05-21-env-username-note-20260521-054204/configs/env.machine2.example \
      /Users/kenallred/Developer/server-setup/configs/env.machine2.example
   ```

2. Verify both files show as modified:
   ```bash
   git -C /Users/kenallred/Developer/server-setup status --short
   ```
   Expected: two `M` entries.

3. Commit `local_agents.py`:
   ```bash
   git -C /Users/kenallred/Developer/server-setup add src/local_ai_stack/local_agents.py
   git -C /Users/kenallred/Developer/server-setup commit -m "Fix LangGraph typing compat: drop future annotations, use native generics

Remove 'from __future__ import annotations' and replace List[]/Dict[] with
list[]/dict[] so LangGraph's get_type_hints resolves AgentState correctly
on Python 3.12."
   ```

4. Commit `configs/env.machine2.example`:
   ```bash
   git -C /Users/kenallred/Developer/server-setup add configs/env.machine2.example
   git -C /Users/kenallred/Developer/server-setup commit -m "Add username substitution note to env.machine2.example"
   ```

5. Remove the worktree and delete its branch:
   ```bash
   git -C /Users/kenallred/Developer/server-setup worktree remove --force \
     /Users/kenallred/Developer/server-setup-local-2026-05-21-env-username-note-20260521-054204
   git -C /Users/kenallred/Developer/server-setup branch -D \
     ai/local/2026-05-21-env-username-note-20260521-054204
   ```

6. Verify clean state:
   ```bash
   git -C /Users/kenallred/Developer/server-setup status
   git -C /Users/kenallred/Developer/server-setup log --oneline -4
   git -C /Users/kenallred/Developer/server-setup worktree list
   ```

## Acceptance criteria
- `git status` on main shows clean working tree
- `git log --oneline -4` shows two new commits at the top
- `git worktree list` shows only the main workspace (no orphaned worktree)
- No other files modified

## Test plan
```bash
# Both commits present
git -C /Users/kenallred/Developer/server-setup log --oneline -4

# Clean tree
git -C /Users/kenallred/Developer/server-setup status

# No orphaned worktrees
git -C /Users/kenallred/Developer/server-setup worktree list

# Content checks
grep "whoami" /Users/kenallred/Developer/server-setup/configs/env.machine2.example
grep "from __future__" /Users/kenallred/Developer/server-setup/src/local_ai_stack/local_agents.py && echo "FAIL" || echo "OK"
```

## Rollback plan
```bash
git -C /Users/kenallred/Developer/server-setup reset --hard HEAD~2
```

## Documentation updates
None required.

## Risks and edge cases
- The worktree must be removed before the branch can be deleted — steps are ordered accordingly.
- `--force` on worktree remove is safe here because the changes will already be committed to `main` before removal.
