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
- [x] **02 — Verify `local-exec-plan` console script.** Confirmed both
  console-script entries resolve: `local-ai-agents` →
  `src/local_ai_stack/local_agents.py:main` (line 528), and
  `local-exec-plan` → `src/local_ai_stack/local_exec_plan.py:main`
  (line 57). No code change required.
- [x] **03 — Drop `/Users/admin/...` hardcoding.** Replaced literals in
  env examples, both HTML files, troubleshooting, smoke/bench scripts.
  Plist template now uses `__HOME__` placeholder (substituted by the
  task-07 install scripts).
- [x] **04 — Fix `\n`-in-JSON bug.** Both scripts now build the JSON
  payload via Python (`json.dumps`) and pipe it into `curl --data-binary`,
  so newlines/quotes/backslashes in prompts are correctly escaped.
- [x] **05 — Layout reconciliation in HTML guide (BIG).** Rewrote
  `docs/html/local_ai_click_by_click_setup_guide.html` from 1,736 lines
  to 424. Steps now: (i) clone repo to `~/ai/local-ai-stack` on both
  Macs, (ii) `uv pip install -e '.[all|mlx]'`, (iii) `scripts/install-symlinks.sh`
  to put helpers on PATH, (iv) use the console scripts (`local-ai-agents`,
  `local-exec-plan`, `smoke-test-endpoints.sh`, etc.) and the register-mcp
  / install-skills helpers. Zero `cat > ...` blocks remain.

### Missing steps (group b)

- [x] **06 — macOS prep section + `docs/MACOS_PREP.md`.** New
  `docs/MACOS_PREP.md` covers hostnames, `pmset`, iCloud Desktop/Docs
  opt-out, FileVault notes, firewall, time sync, UPS. HTML guide gets a
  new "Part 0 · macOS prep" section with the minimum required commands
  and a link to the full doc.
- [x] **07 — Launchd autostart for M1 + M2.** Chose single
  `com.localai.workers.plist.template` (M2) rather than per-server plists
  to match the existing M1 pattern; both invoke their respective
  start-script. Added `scripts/install-launchd-machine{1,2}.sh` that
  substitute `__HOME__`, write to `~/Library/LaunchAgents/`, and
  bootstrap into `gui/$(id -u)/`. New "Part VII · Autostart on boot"
  section in the HTML guide.
- [x] **08 — True end-to-end verification section.** New section
  `#smoke-e2e` ("14b / End-to-end acceptance test") walks the user
  through: create a disposable target repo, write a tiny plan, run it
  with `local-exec-plan` (or `/delegate-local` once Part VI is done),
  and verify four pass conditions including a worktree on its own
  `ai/local/…` branch and a reviewer JSON with `"approved": true`.
- [x] **09 — Re-running / idempotency notes.** New section
  `#rerun-idempotency` ("25 / Reference · Re-running this guide") with a
  table covering every install command in the guide: which are safe to
  rerun, which require a pre-step (e.g., `claude mcp remove ...`),
  which destroy user edits (`.env`).
- [x] **10 — Backup / disaster recovery doc.** New `docs/BACKUP.md`
  with: a path taxonomy (what to back up, what to skip), an explicit
  decision tree for `~/ai/models/` (200+ GB), and an 8-step disaster
  recovery rebuild order. Linked from the HTML guide Security section.

### Supporting (group c)

- [x] **11 — Missing M2 launchd plists.** Covered by task 07.
- [x] **12 — `scripts/install-launchd-machine{1,2}.sh`.** Covered by task 07.
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
