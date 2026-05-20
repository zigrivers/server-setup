# AI Development Workflow

This repository uses a hybrid AI workflow.

## Roles

Frontier models such as Claude Code and Codex are used for:

- architecture planning
- implementation plans
- design review
- documentation
- final high-level review

Local open-source models are used for:

- implementation
- test creation
- debugging
- local code review
- repeated fix/review loops

## Required handoff pattern

For any non-trivial feature, create a plan under:

```text
plans/YYYY-MM-DD-feature-name.md
```

The plan must include:

1. Goal
2. Non-goals
3. Current system summary
4. Proposed architecture
5. Files expected to change
6. Step-by-step implementation tasks
7. Acceptance criteria
8. Test plan
9. Rollback plan
10. Documentation updates required
11. Risks and edge cases

## Frontier model rules

When asked to plan:

- Do not implement source-code changes unless explicitly asked.
- Prefer writing or updating files under `docs/` and `plans/`.
- Produce precise acceptance criteria.
- Include exact commands to run tests.
- Include migration and rollback notes when relevant.

When asked to review:

- Compare implementation against the plan.
- Focus on architecture, correctness, security, maintainability, and docs.
- Do not rewrite the implementation unless explicitly asked.

## Local agent rules

When executing a plan:

- Work in an isolated branch or worktree.
- Implement the plan as written.
- Add or update tests.
- Run relevant test/lint/typecheck commands.
- Stop after reviewer approval or after three failed review loops.
- Do not touch secrets, credentials, deployment config, or unrelated files.

## Human rules

The human developer must approve:

- the plan before implementation
- dependency additions
- database migrations
- destructive commands
- final merge
