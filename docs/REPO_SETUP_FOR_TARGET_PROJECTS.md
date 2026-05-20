# Setting Up Other Project Repos

In any repo where you want to use this workflow, add:

```text
AGENTS.md
CLAUDE.md
docs/ai/AI_WORKFLOW.md
plans/
```

You can copy starter templates from:

```text
docs/repo-templates/
```

Then commit them:

```bash
git add AGENTS.md CLAUDE.md docs/ai/AI_WORKFLOW.md plans/.gitkeep
git commit -m "Add hybrid AI workflow instructions"
```

Use Claude/Codex for planning:

```text
Create a plan under plans/YYYY-MM-DD-feature.md. Do not implement yet.
```

Use local execution:

```bash
local-exec-plan plans/YYYY-MM-DD-feature.md --workspace .
```
