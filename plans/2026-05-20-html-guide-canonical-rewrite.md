# Plan: Make the HTML guide the canonical click-by-click Mac Studio setup

Status: in-progress
Owner: @zigrivers (executor: Claude Opus 4.7)
Started: 2026-05-20

## Goal

This repo's primary deliverable is a single HTML step-by-step guide at
`docs/html/local_ai_click_by_click_setup_guide.html` that a user can follow
click-by-click to take two fresh Mac Studios from out-of-the-box to a working
split-machine local AI stack (Machine 1 control plane + Machine 2 inference
worker over Thunderbolt Bridge).

All supporting Markdown docs, scripts, configs, and source code in the repo
must be consistent with that HTML guide and the HTML guide must use them
rather than duplicate them inline.

## Non-goals

- Designing or training new models
- Rewriting the LangGraph agent loop or MCP server semantics
- Supporting non-Apple-Silicon hardware
- Building a CI pipeline

## Current state (audit summary)

Two parallel layouts exist:

- **Layout A** (HTML guide): everything hand-written via `cat > ... <<EOF`
  into `~/ai/...`, three separate venvs, never clones this repo.
- **Layout B** (repo + Markdown docs): clone repo to `~/ai/local-ai-stack`,
  one venv, `pip install -e .[all]`, console scripts, `install-symlinks.sh`.

The repo currently has no `[build-system]` table, `huggingface_hub` is
mis-placed in extras, `/Users/admin/...` is hardcoded, M2 has no launchd
plist, macOS prep and end-to-end verification are missing.

## Proposed direction

Make **Layout B the canonical layout** (repo is source of truth). Rewrite
the HTML guide to clone the repo first and reference its scripts/configs
instead of hand-writing duplicates. Fill the remaining holes (macOS prep,
launchd, backup, verification).

## Files expected to change

- `pyproject.toml`
- `docs/html/local_ai_click_by_click_setup_guide.html`
- `docs/html/local_ai_infrastructure_overview.html`
- `docs/html/README.md`
- `docs/SETUP.md`, `docs/OPERATIONS.md`, `docs/TROUBLESHOOTING.md`,
  `docs/EXPERIMENTAL_MTP.md`
- `docs/MCP.md` (new)
- `docs/MACOS_PREP.md` (new)
- `docs/BACKUP.md` (new)
- `configs/env.machine1.example`, `configs/env.machine2.example`
- `configs/launchd/com.localai.developer.plist.template` (new)
- `configs/launchd/com.localai.reviewer.plist.template` (new)
- `scripts/bench-chat-endpoint.sh`
- `scripts/smoke-test-endpoints.sh`
- `scripts/m1-ai-status.sh`
- `scripts/install-launchd-machine1.sh` (new)
- `scripts/install-launchd-machine2.sh` (new)
- `scripts/preflight.sh` (new)
- `README.md`
- `REPO_FILE_MANIFEST.md` (deleted or regenerated)

## Task list — one PR per task, squash-merge

Each task ships in its own branch `feat/NN-short-slug`, opens a PR, gets
squash-merged into `main`, then the next task starts from refreshed `main`.

### Must-fix (group a)

- [x] **01 — pyproject build-system + huggingface_hub.** Add explicit
  `[build-system]` (hatchling). Move `huggingface_hub[hf_xet]` into base
  deps so `hf` CLI is available with any extra. Update `[all]` accordingly.
- [ ] **02 — Verify `local-exec-plan` console script.** Confirm
  `src/local_ai_stack/local_exec_plan.py` has a `main()` function matching
  the `pyproject.toml` `[project.scripts]` entry. Add it if missing.
- [ ] **03 — Drop `/Users/admin/...` hardcoding.** Replace literals in
  `configs/env.machine{1,2}.example` and HTML guide §09 with `$HOME` /
  templated paths.
- [ ] **04 — Fix `\n`-in-JSON bug.** Rewrite `bench-chat-endpoint.sh:19`
  and `smoke-test-endpoints.sh:15` to send real JSON (heredoc + `--data @-`
  or `python -c`).
- [ ] **05 — Layout reconciliation in HTML guide (BIG).** Rewrite the HTML
  guide to: clone repo first, run `scripts/install-symlinks.sh`,
  `pip install -e .[all]`, use console scripts, call
  `install-claude-skills.sh` and `register-mcp-{claude,codex}.sh` instead
  of inline `cat > ...` blocks. Reduce file substantially.

### Missing steps (group b)

- [ ] **06 — macOS prep section + `docs/MACOS_PREP.md`.** Sleep,
  iCloud, FileVault, hostname, `caffeinate` notes. Linked from HTML guide.
- [ ] **07 — Launchd autostart for M1 + M2.** Create
  `configs/launchd/com.localai.{developer,reviewer}.plist.template`. Add
  `scripts/install-launchd-machine{1,2}.sh` to render templates with real
  `$HOME` and `launchctl bootstrap`. New HTML guide section.
- [ ] **08 — True end-to-end verification section.** From a sample
  project repo, invoke `/delegate-local` (or `local-exec-plan`) on a tiny
  plan, confirm worktree, confirm reviewer JSON. Add to HTML guide.
- [ ] **09 — Re-running / idempotency notes.** A short section in the
  HTML guide explaining what is safe to re-run vs what overwrites
  user-customized state (notably `.env`).
- [ ] **10 — Backup / disaster recovery doc.** `docs/BACKUP.md` covering
  `~/ai/models/` (200+ GB, not in iCloud), `.env`, agent memory.

### Supporting (group c)

- [ ] **11 — Missing M2 launchd plists.** Covered by task 07.
- [ ] **12 — `scripts/install-launchd-machine{1,2}.sh`.** Covered by task 07.
- [ ] **13 — `scripts/preflight.sh`.** TB Bridge ping + SSH to M2 + `hf`
  auth + three endpoints up. Wire into HTML guide post-install step.
- [ ] **14 — `scripts/render-html.sh` (deferred).** Long-term drift risk
  if HTML and Markdown diverge. Either build an MD→HTML renderer or add a
  manual cross-check checklist. Decision recorded in this plan as
  "checklist not renderer" to avoid scope creep.

### Nice-to-haves (group d)

- [ ] **15 — Delete or regenerate `REPO_FILE_MANIFEST.md`.** Currently
  lists `.pyc` files (drift). Delete unless there's a strong reason to
  keep a hand-maintained index.
- [ ] **16 — `docs/MCP.md`.** Narrative doc for the MCP bridge so it
  isn't only described inside the HTML guide.
- [ ] **17 — Document `MTP35_MODEL=mtplx` exception** in
  `docs/EXPERIMENTAL_MTP.md` so the alias doesn't look like a contradiction
  to the "never use aliases" rule.
- [ ] **18 — Remove `Local AI Multi-Agent Setup.zip`** from working dir
  (already git-ignored; just delete the file).
- [ ] **19 — Status `m1-ai-status.sh` MTP port parity.** Either add 8004
  to M1 status or remove from M2 status; pick "add to M1" since M1 is the
  status hub.
- [ ] **20 — Top-of-HTML-guide canonicity note.** Add a one-line banner
  saying "this guide is the canonical setup; Markdown docs are reference."

## Acceptance criteria

- Every task above is checked in this file.
- Every task ships as its own PR, squash-merged to `main`.
- After all tasks: a user with two new Mac Studios can open
  `docs/html/local_ai_click_by_click_setup_guide.html` in a browser and,
  by following only that file, end up with a working stack — including
  launchd autostart on reboot.
- HTML guide no longer hand-writes scripts that exist in `scripts/` or
  source files that exist in `src/`.

## Test plan

- `python -c "import local_ai_stack"` after `uv pip install -e .` works.
- `local-exec-plan --help` and `local-ai-agents --help` print usage.
- `scripts/preflight.sh` reports honestly when endpoints are down.
- HTML guide passes a manual read-through: every command block either
  references a repo file or has been justified as inline.

## Rollback plan

Each PR is independent and squash-merged. To roll back any single change:
`git revert <merge-sha>`. Layout-reconciliation PR (task 05) is the only
high-blast-radius one; its revert restores the old hand-written HTML guide.

## Risks

- Layout-reconciliation PR is large and may be hard to review in one go.
  Mitigation: keep the diff to the HTML file scoped to structural changes;
  do not also rewrite prose unrelated to the layout decision.
- Launchd `bootstrap`/`bootout` syntax differs by macOS version. Plists
  ship as templates; install scripts probe `sw_vers` and choose the right
  invocation.
