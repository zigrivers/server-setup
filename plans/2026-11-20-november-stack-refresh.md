# November 2026 stack refresh

Status: **approved 2026-11-20 and implemented** (groups A-D). Corrections made during the work are
listed under "Changes from the plan" at the end.

## Goal

Bring the tools, skills, scripts and documents of the two-Mac local AI stack up to date, based on a
review and web research done on 2026-11-20. Keep the current models.

## Non-goals

- No model swap. Research (with a second, skeptical verification pass) found no model released
  since 2026-10-21 with evidence of beating the current ones in their roles.
- No change to the two-machine architecture.
- No work on Machine 2 until it is reachable again (see "Blocker").
- No migration to MCP Python SDK 2.x, Next.js 16, or a regenerated set of HTML guides.

## Blocker (owner action)

Machine 2 has been unreachable since 2026-11-08 21:11. `ifconfig bridge0` reports
`status: inactive`, ping to `10.10.10.2` loses every packet, and Wake-on-LAN has no effect. The
Mac is off or asleep, or the Thunderbolt cable is out. Developer (`:8002`) and Reviewer (`:8003`)
are down; `local_review` still works because it uses the Orchestrator on Machine 1.

## Current system summary

| Item | Installed | Latest (2026-11-20) | Verdict |
|---|---|---|---|
| Orchestrator model | Jundot/Qwen3.6-35B-A3B-oQ4e-mtp | no official Qwen3.8 A3B model exists | keep |
| Developer / Reviewer model | Jundot/Qwen3.8-27B-oQ8e-mtp | no proven better model; Qwen 4 is hosted only | keep |
| Embeddings | Qwen3-Embedding 0.6B / 8B | no MLX build of a better model | keep |
| oMLX (Machine 1) | 0.7.2 | 0.8.0 (2026-11-18), 0.7.3 (2026-10-31) | decision D1 |
| mlx / mlx-lm | 0.32.4 / rollback pair 0.31.x | 0.32.4 / 0.32.2 | keep |
| MCP Python SDK | 1.27.1, unpinned upper bound | 1.30.0 (security fixes); 2.x breaks our import | upgrade, pin `<2` |
| LangGraph | 1.2.0 | 1.2.24 (SDK advisory fixed in 1.2.14) | upgrade |
| Qdrant | container stopped, `:latest` | v1.20.2 | decision D2 |
| Ollama | server 0.40.13, client 0.40.16 | 0.40.16 | decision D3 |
| Dashboard web | Next.js 15.5.19 | 15.5.29 | **done** (local-ai-dashboard PR #18) |

Watch list, no action now: DeepSeek-V4.1-Flash-1017 (first reviewer trial candidate once Machine 2
is back and oMLX is upgraded; public scores were measured at full precision, local builds are
3-bit), GLM-5.3-Flash (second), Ornith-1.5-35B-A3B and Qwen3.8-Flash-Next (orchestrator), open
Qwen 4 weights under `huggingface.co/Qwen`, the 2026-11-19 re-quantized Jundot builds.

## Proposed changes

No architecture change. Four groups of small fixes.

### A. Skills and MCP bridge

1. `skills/claude/*/SKILL.md` and `docs/MCP.md:124-127`: use the full tool names
   (`mcp__local-ai-delegate__local_ai_status`, `…__local_review`, `…__run_local_plan`,
   `…__git_local_summary`).
2. `skills/claude/local-review/SKILL.md:18-19` and `docs/MCP.md:160`: the review comes from the
   Orchestrator on Machine 1 by default, not the Reviewer.
3. `skills/claude/local-ai-status/SKILL.md`: add the Machine 2 link check
   (`ifconfig bridge0 | grep status`, `ping -c1 -t2 10.10.10.2`), say what still works when
   Machine 2 is down, say "always `127.0.0.1`, never `localhost`", and point details at
   `~/Developer/server-setup/docs/OPERATIONS.md`.
4. `mcp/local_delegate_mcp/server.py`: append a one-line note to the status output when the
   Orchestrator is up and a worker is down; replace the string-prefix allowed-root test with a
   path-parent test (line 45); catch model-discovery errors in `local_review` (line 220). One test
   for the sibling-directory case.
5. Remove the stale second copy `.agents/skills/{delegate-local,local-review,local-ai-status}`;
   point `scripts/install-antigravity-skills.sh:9` at `skills/claude`; update `README.md:39-42`.
6. Re-sync the installed copies in `~/.agents`, `~/.codex`, `~/.grok`, `~/.cursor`,
   `~/.gemini/antigravity-cli`.

### B. Scripts

1. `scripts/m1-ai-status.sh:13,18,23`: add `--max-time 5` to each `curl`. Today the script hangs
   for more than 90 seconds when Machine 2 is down.
2. `scripts/m2-watchdog.sh:496-503`: restart the meter only on the transition into "down", not on
   every cooldown expiry. During this outage it restarted the meter about every 5.5 minutes
   (2,776 runs, 3,486 `EADDRINUSE` crashes), which lost telemetry and failed nightly reports.
3. `scripts/check-mlx-blockers.sh`: fix the dead DeepSeek probe (check the `deepseek_v4`
   directory), drop the merged PR #1410 check, set `BASELINE_MLX_LM="0.32.2"`.

### C. Dependencies

1. `pyproject.toml`: `mcp>=1.30,<2`, `fastmcp>=3.3,<4`; upgrade `mcp` to 1.30.0 in the venv that
   runs the bridge.
2. `langgraph>=1.2.24,<1.3`.

### D. Documents

Fix model and runtime drift: `docs/ARCHITECTURE.md:29,36`, `CLAUDE.md:28,32`, `AGENTS.md:29`,
`docs/AGENT_BRIEF.md:13,20-25,55-56,67-73`, `README.md`, `docs/TROUBLESHOOTING.md`,
`docs/dev-stack-models.md`. Add a "Historical (June 2026, pre-oMLX)" banner to `docs/html/*`.
Add a pointer to the eval harness (`~/Developer/local-ai-dashboard/src/toolcalleval`,
`src/modeleval`) next to the gate table in `docs/MODELS.md`.

## Decisions for the owner

- **D1, oMLX.** (a) Recommended: wait for 0.8.1 or two weeks, then upgrade both Macs together.
  0.8.0 is two days old and changes concurrency defaults; its speed numbers are the maintainer's
  own and were measured under different conditions. (b) Upgrade Machine 1 to 0.7.3 now, with the
  gates in `docs/OMLX.md` plus a check for issue #5301. (c) Upgrade Machine 1 to 0.8.0 now.
- **D2, RAG.** Qdrant is stopped and the RAG proxy has zero collections. (a) Recommended if RAG
  is unused: stop the RAG proxy. (b) Start Qdrant, set it to restart, pin `v1.20.2`, add a status
  check.
- **D3, Ollama.** The Homebrew job `sh.brew.ollama` crash-loops because the Ollama app already
  holds port 11434 (64 MB log). Recommended: `brew services stop ollama`, then restart the app so
  the server runs 0.40.16. Separately: keep or remove `gpt-oss:120b` (65 GB, 9 months old).
- **D4, port clash.** The `nibble` Docker project publishes `0.0.0.0:8001-8003` on Machine 1, so
  `localhost:8001` reaches the wrong service. Recommended: remap its host ports (for example
  `127.0.0.1:18001:8001`) in that project.
- **D5, dashboard exposure.** The dashboard listens on every network interface with no password.
  (a) Recommended: set `DASHBOARD_PASSWORD` in `~/ai/dashboard/dashboard.env`. (b) Bind to
  `127.0.0.1` only, which blocks viewing from other devices.
- **D6, stale checkout.** `~/ai/local-ai-stack` on Machine 1 is a June clone, 89 commits behind.
  Recommended: replace it with a symlink to `~/Developer/server-setup`.
- **D7, Cursor and Grok.** They have the three skills but no `local-ai-delegate` registration.
  Register the bridge there, or remove the skills from those two agents.

## Dashboard follow-ups (repo `~/Developer/local-ai-dashboard`, separate PRs)

None of the October review's findings were fixed. In order: exclude watchdog pings from every
metric (`apps/web/lib/queries.ts`); skip collector self-heal when the peer is provably down
(`src/collector/main.ts`); mark stale machine data on the Hardware tab; show the last model ever
seen for an endpoint; reword the "1/3 endpoints" alert; show one line instead of ten regressions
when a machine is unreachable; add timestamps to meter and collector logs.

## Files expected to change

`skills/claude/{local-ai-status,local-review,delegate-local}/SKILL.md`,
`mcp/local_delegate_mcp/server.py`, `tests/test_local_delegate_server.py`,
`scripts/{m1-ai-status,m2-watchdog,check-mlx-blockers,install-antigravity-skills}.sh`,
`pyproject.toml`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/*.md` listed above,
`docs/html/*`; removal of `.agents/skills/{delegate-local,local-review,local-ai-status}`.

## Steps

1. Branch. Apply group B with tests first (the watchdog has tests under `tests/`).
2. Apply group A; run the bridge tests; call all four MCP tools.
3. Apply group C; re-run the tests and the four tools.
4. Apply group D.
5. Re-sync installed skill copies. PR, checks, merge.
6. After Machine 2 is back: pull the checkout there, confirm the watchdog copy matches, then
   handle D1.

## Acceptance criteria

- `scripts/m1-ai-status.sh` finishes in under 20 seconds with Machine 2 down.
- With Machine 2 down for 30 minutes, the meter restarts at most once.
- `local_ai_status` output names what still works when a worker is down.
- No document names MiMo, BF16, or `mlx_lm.server` as the current default.
- `pip show mcp` reports 1.30.x; all four bridge tools answer.

## Test plan

```bash
cd ~/Developer/server-setup
.venv/bin/python -m pytest tests -q
time bash scripts/m1-ai-status.sh
bash scripts/check-mlx-blockers.sh
grep -rnE "mimo|bf16" docs/ARCHITECTURE.md CLAUDE.md AGENTS.md docs/AGENT_BRIEF.md -i
```

Then call `local_ai_status`, `git_local_summary` and `local_review` through the bridge.

## Rollback

Every change is a normal commit: `git revert` the merge. For the `mcp` upgrade:
`uv pip install --python .venv/bin/python 'mcp==1.27.1'`. Installed skill copies are backed up to
`~/.local/state/agent-instruction-backups/<date>/` before the re-sync.

## Documentation updates

Covered by group D. `docs/OPERATIONS.md` gains one line on the new watchdog behaviour.

## Risks and edge cases

- The watchdog change must still restart the meter when Machine 2 comes back; the existing
  meter-wedged path (`scripts/m2-watchdog.sh:437-455`) covers this and must be tested.
- Machine 2 keeps the old watchdog and status scripts until it is reachable and pulls.
- `mcp` 1.30 is the same major version, but the bridge must be re-tested because every agent
  depends on it.
- Research confidence is medium for the watch-list models: no single-M3-Ultra decode speed is
  published for DeepSeek V4.1 Flash, so any trial must measure locally first.

## Changes from the plan

- Machine 2 came back online on 2026-11-20 during the work; the Blocker section is history.
- Group C was wrong about the bridge. Its venv (`~/Developer/server-setup/.venv`) already ran
  MCP Python SDK 2.2.0 with `mcp>=2,<3`; the research had read the stale `~/ai/local-ai-stack`
  clone. The libraries were updated inside their current major versions instead of capped at 1.x.
- The DeepSeek probe in `scripts/check-mlx-blockers.sh` was removed, not repaired: the V4 weights
  are deleted and the V4.1 loader is already upstream.
- The watchdog restarts the meter at most once per outage. If Machine 2 drops inside the cooldown
  of an earlier recovery, that outage gets no meter restart; the meter-wedged path covers the
  return. That path is unchanged code and has no new test.
- D1: oMLX 0.8.0 was trialled side by side with 0.7.2; see `docs/OMLX.md`.
