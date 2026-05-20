# Local AI smoke test

## Goal

Update README.md with a short section called "Local AI Smoke Test".

## Non-goals

- Do not modify source code.
- Do not add dependencies.

## Files expected to change

- README.md

## Tasks

1. Open README.md.
2. Add a section titled "Local AI Smoke Test".
3. Mention that the split-machine local multi-agent system can execute frontier-generated plans.

## Acceptance criteria

- README.md contains the heading "Local AI Smoke Test".
- No source code files are changed.

## Test plan

Run:

```bash
git diff -- README.md
```

## Rollback plan

Revert the README change.

## Documentation updates

README only.

## Risks and edge cases

None. This is a safe smoke test.
