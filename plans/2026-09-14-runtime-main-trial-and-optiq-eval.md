# 2026-09-14 — mlx-lm main trial (Metal leak), OptiQ-4bit eval, Flash-Next watch

## Goal

Make the three mlx endpoints stop crashing on long completions without changing which
model answers, and find out by measurement whether a 4-bit mixed-precision build of the
Developer/Reviewer weights is faster at **no** loss of review recall. Also extend the
blocker watcher so the next real model upgrade (Qwen3.8-Flash-Next) is noticed the day it
becomes loadable.

Research behind this plan (2026-09-14): no checkpoint that loads on a released `mlx-lm` beats
what is served today. GLM-5.3 has the same IndexShare layout as 5.2 (PR #1410 still open),
DeepSeek-V4.1 is a new `deepseek_v41` arch with no upstream code, Kimi K3 is a 2.8T writing
model that would need M2 to itself, Gemma 4 26B-A4B scores 80 on LiveCodeBench v6 against the
27B's 90. The one clear upgrade, Qwen3.8-Flash-Next (125B/6B-active, beats Qwen3.8-27B on
every coding benchmark), waits on mlx-lm PR #1788.

## Non-goals

- No new model on any production endpoint. The weights on `:8001`/`:8002`/`:8003` do not change
  unless step B's eval passes its gate, and even then only the quantization changes.
- No change to ports, the meter, the watchdog's restart logic, or the two-machine layout.
- No third-party model code (DeepSeek-V4, GLM IndexShare, `qwen4_exp`) in any serving venv.
- No `pip install --upgrade` inside the existing `~/ai/.venv` on either machine. It stays at
  mlx-lm 0.31.3 as the rollback target.

## Current system (verified live 2026-09-14)

| Endpoint | Model | Runtime | Crashes in log |
|---|---|---|---|
| M1 `127.0.0.1:8001` orchestrator | Qwen3.6-35B-A3B heretic mixed-9bit, 38 GB | mlx-lm 0.31.3, mlx 0.31.2 (`~/ai/.venv`) | 8 |
| M2 `10.10.10.2:8002` developer | Qwen3.8-27B 8-bit, 28 GB | same versions (`/Users/admin/ai/local-ai-stack/.venv`) | 1 |
| M2 `10.10.10.2:8003` reviewer | same weights as developer | same | 1 |

Both machines are M3 Ultra, 512 GiB, macOS 26.x, Python 3.12. Each also has `~/ai/mtp-venv`
(mlx 0.32.1, mlx-vlm 0.6.15) — proof that a second venv on a newer mlx coexists fine.

Upstream state:

- `mlx-lm` 0.31.3 (2026-04-22) is still the newest PyPI release. `main` is at
  `d8f7f88d8a1f730a761a49f59b2d547ce571f431` (2026-09-14) with five months of unreleased fixes.
- Metal-buffer leak (`[metal::malloc] Resource limit (499000) exceeded`): issues #1662 and #1332
  **closed on main 2026-08-27**. Issue #1845 (2026-09-04) is **still open**: the batched-decode
  path of hybrid SSM models (`qwen3_5`, `qwen3_5_moe` — exactly what we serve) still leaks one
  buffer per SSM layer per generated token, crashing a single completion at roughly
  `499000 / (ssm_layers − 1)` tokens (≈10.6k tokens for the 27B). PR #1872, a workaround, was
  closed unmerged 2026-09-10.
- So `main` is a **partial** fix. Whether it helps our traffic is an empirical question — hence a
  trial with a deterministic reproducer, not a blind upgrade.
- `main` also carries "Fix Qwen3.6 converted norm sanitization (#1623)", which may change the
  Orchestrator's numerics. That must be measured, not assumed harmless.
- `mlx-community/Qwen3.8-27B-OptiQ-4bit`: 20.7 GB (vs 28 GB), per-layer 4/8-bit mix chosen by a
  KL sensitivity pass. Loads text-only under stock `mlx-lm`. 14.5k downloads.

## Proposed architecture

Nothing structural changes. Three additive knobs:

1. Each launcher (`start-orchestrator.sh`, `start-developer.sh`, `start-reviewer.sh`) reads an
   optional per-role venv override from `.env` (`ORCH_VENV`, `DEV_VENV`, `REVIEW_VENV`) and falls
   back to `$REPO_DIR/.venv`. Unset → byte-for-byte today's behaviour.
2. A second venv per machine, `~/ai/venv-mlx-main`, holding `mlx-lm` pinned to one commit.
   Switching a role between venvs is one line in `.env` plus a restart.
3. `scripts/check-mlx-blockers.sh` also watches PR #1788 (Flash-Next).

```
.env:  REVIEW_VENV=/Users/admin/ai/venv-mlx-main     ← one role at a time
       DEV_VENV=…                                     ← only after the reviewer soak passes
M1 plist env: ORCH_VENV=/Users/kenallred/ai/venv-mlx-main  ← last, after M2 is proven
```

## Files expected to change

- `scripts/start-orchestrator.sh`, `scripts/start-developer.sh`, `scripts/start-reviewer.sh` —
  venv override (3 lines each; `.env` must be sourced *before* `activate`).
- `scripts/check-mlx-blockers.sh` — watch PR #1788 and mention Flash-Next in the notify text.
- `docs/MODELS.md` — runtime column per endpoint; OptiQ eval result table.
- `docs/TROUBLESHOOTING.md` — leak section: which sites are fixed on main, which remain (#1845),
  and the reproducer command.
- `docs/OPERATIONS.md` — how to flip a role's venv and back.
- On M2 (outside the repo): `/Users/admin/ai/local-ai-stack/.env` (backup first),
  `~/ai/venv-mlx-main`, `~/ai/models/developer-qwen38-27b-optiq4`.
- On M1: `~/ai/venv-mlx-main`; the orchestrator LaunchAgent plist env (only in step A6).
- `local-ai-dashboard`: one new `eval/modeleval-*.json` config per eval run; results under
  `eval/results/2026-09-*`. No source changes.

## Step-by-step implementation tasks

Every step names the machine. `ssh m2` reaches M2 as `admin`.

### A. Runtime trial — mlx-lm `main`, pinned

**A1 — build the trial venv on M2.** Pin the commit so both machines and the docs agree on
exactly what was tested.

```bash
ssh m2
MLX_LM_SHA=d8f7f88d8a1f730a761a49f59b2d547ce571f431
python3.12 -m venv ~/ai/venv-mlx-main
~/ai/venv-mlx-main/bin/pip install --upgrade pip
~/ai/venv-mlx-main/bin/pip install "git+https://github.com/ml-explore/mlx-lm@${MLX_LM_SHA}"
~/ai/venv-mlx-main/bin/pip list | grep -iE '^mlx'     # record versions in the plan's log
```

Expect it to pull `mlx` ≥ 0.32. If it pins something older than 0.32.2, note it; do not force.

**A2 — write the reproducer and prove it is red on 0.31.3.** Start a temporary server from the
*stock* venv on a spare port with the served weights and ask for one very long completion.
Issue #1845 predicts a crash near 10.6k generated tokens on the 27B.

```bash
# M2, stock venv, spare port — production endpoints untouched
source ~/ai/local-ai-stack/.venv/bin/activate
mlx_lm.server --model /Users/admin/ai/models/developer-qwen38-27b-8bit \
  --host 127.0.0.1 --port 8009 --max-tokens 20000 >> ~/ai/logs/trial-8009.log 2>&1 &

# from M1 or M2 — one completion, 16k budget, forced long output
curl -s http://127.0.0.1:8009/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "/Users/admin/ai/models/developer-qwen38-27b-8bit",
  "messages": [{"role":"user","content":"Write the integers from 1 to 6000, one per line, no commentary."}],
  "max_tokens": 16000, "temperature": 0,
  "chat_template_kwargs": {"enable_thinking": false}
}' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("usage"), d.get("error"))'
grep -c "Resource limit" ~/ai/logs/trial-8009.log     # expect ≥ 1 → RED
pkill -f 'mlx_lm[.]server.*--port 8009'
```

Save this as `scripts/repro-metal-leak.sh` (port, model path and budget as env vars) so the
same command runs on M1 against the Orchestrator and later against any release candidate.

**A3 — run the reproducer green (or not) on `main`.** Same command, `~/ai/venv-mlx-main`
activated. Record: did it complete, how many tokens, tok/s, and whether the log shows the
traceback. If it still crashes at roughly the same token count, #1845 is confirmed unfixed for
this model and the trial stops here for M2 (go to A5 for the Orchestrator, whose failure mode
differs). Either way the result goes in `docs/TROUBLESHOOTING.md`.

**A4 — quality guard.** Same weights, two runtimes, same eval. On M2 start the `main` server
on `:8009` (27B, `--max-tokens 8192`, same flags as `start-reviewer.sh`). In `local-ai-dashboard`
add `eval/modeleval-2026-09-runtime-main.json` with two arms:

```json
{ "name": "qwen3.8-q8-mlxlm-0.31.3", "baseUrl": "http://10.10.10.2:8003/v1", "maxTokens": 12000 }
{ "name": "qwen3.8-q8-mlxlm-main",   "baseUrl": "http://10.10.10.2:8009/v1", "maxTokens": 12000 }
```

`npx tsx src/modeleval/run.ts eval/modeleval-2026-09-runtime-main.json`. Gate in acceptance
criteria. Stop the `:8009` server after.

**A5 — soak on the Reviewer (7 days).** Flip only the Reviewer:

```bash
ssh m2 'cp ~/ai/local-ai-stack/.env ~/ai/local-ai-stack/.env.bak-20260914 && \
        echo "REVIEW_VENV=/Users/admin/ai/venv-mlx-main" >> ~/ai/local-ai-stack/.env && \
        pkill -f "mlx_lm[.]server.*--port 8003"'          # launchd relaunches it
ssh m2 'sleep 90; curl -s http://10.10.10.2:8003/v1/models | head -c 200'
```

Baseline the day before: `grep -c "Resource limit" ~/ai/logs/reviewer.log` plus the meter's
reviewer failure count from the dashboard. Compare after seven days. Then the Developer
(`DEV_VENV`), another seven days.

**A6 — Orchestrator on M1, last.** Build `~/ai/venv-mlx-main` on M1 the same way (same SHA).
Run the reproducer against the Orchestrator weights on `:8009` first — its crashes cluster on
>150k-token *prompts*, a different site from #1845, so `main` may fix it outright. Run the A4
eval with the Orchestrator arms (`:8001` vs `:8009`) because of the #1623 norm change. Only then
set `ORCH_VENV` in the LaunchAgent's `EnvironmentVariables` and `launchctl kickstart -k`.

### B. OptiQ-4bit eval (Developer/Reviewer weights only)

**B1 — download to M2** (21 GB):

```bash
ssh m2 'source ~/ai/local-ai-stack/.venv/bin/activate && \
  hf download mlx-community/Qwen3.8-27B-OptiQ-4bit --local-dir ~/ai/models/developer-qwen38-27b-optiq4'
```

**B2 — serve on the spare port** from the stock venv (`:8009`, `--max-tokens 8192`, same flags
as the reviewer). Confirm `/v1/models` and one short completion.

**B3 — three-arm eval** in `local-ai-dashboard`, `eval/modeleval-2026-09-optiq.json`:

```json
{ "name": "qwen3.8-q8",     "baseUrl": "http://10.10.10.2:8003/v1", "maxTokens": 12000 }
{ "name": "qwen3.8-optiq4", "baseUrl": "http://10.10.10.2:8009/v1", "maxTokens": 12000 }
```

Also run `scripts/bench-chat-endpoint.sh` against both for tok/s and resident memory
(`ps -o rss` on the two server PIDs) on the merge-intervals prompt already used in
`docs/MODELS.md`.

**B4 — decide by the gate below.** Pass → `DEV_MODEL_PATH`/`REVIEW_MODEL_PATH` to the OptiQ
path, `METER_DEV_MODEL`/`METER_REVIEW_MODEL` in `~/ai/dashboard/dashboard.env` to match
(model ids are load instructions — see MODELS.md), restart both workers and the meter. Fail →
leave the weights on disk, record the numbers, done.

### C. Blocker watcher

Add PR #1788 to `scripts/check-mlx-blockers.sh` (`pr1788=$state` in the state string, a
`news+=("Qwen3.8-Flash-Next: mlx-lm PR #1788 merged")` line, and Flash-Next in the notify
message). Keep the weekly cadence.

## Acceptance criteria

- **A2/A3:** the reproducer crashes the stock server and the outcome on `main` is recorded
  either way. A "still crashes" result is a valid outcome, not a failure of the plan.
- **A4 (runtime quality gate):** on the 18-bug/4-clean set, the `main` arm has recall within one
  bug of the stock arm (≥ 15/18 when stock scores 16/18), **zero** false alarms, zero empty
  answers, and the blind judge does not prefer stock by more than 2 net cases. tok/s within ±10%.
- **A5:** after seven days on the Reviewer, `Resource limit` count and meter-reported reviewer
  failures are ≤ the seven days before, with no new class of error in `reviewer.log`.
- **B (OptiQ gate):** recall ≥ 16/18, false alarms 0/4, empty answers 0, judge net preference
  for q8 ≤ 2 cases, **and** tok/s ≥ 1.2× q8. Anything less → stay on 8-bit. Speed never buys
  a missed bug.
- **C:** `bash scripts/check-mlx-blockers.sh` exits 0 and its log line includes `pr1788=open`.
- Launchers with no `*_VENV` set start exactly as before (`bash -n` clean; smoke test passes).

## Test plan

- `scripts/smoke-test-endpoints.sh` after every restart of a production endpoint.
- `scripts/repro-metal-leak.sh` red on 0.31.3, then on `main` (record result).
- `npx tsx src/modeleval/run.ts <config>` for A4, A6 and B3; results committed under
  `eval/results/2026-09-*` in `local-ai-dashboard`.
- `npx vitest run src/modeleval` still green (no source change expected, but it is the gate).
- `scripts/bench-chat-endpoint.sh` for tok/s on each arm.
- Seven-day soak counters for A5 (log grep + meter telemetry) before and after.

## Rollback plan

- Any role: delete its `*_VENV` line from `.env` (or restore `.env.bak-20260914`), kill the
  server; launchd relaunches it from the stock venv. On M1 remove `ORCH_VENV` from the plist
  and `launchctl kickstart -k gui/$(id -u)/com.localai.orchestrator`.
- The stock `~/ai/.venv` on both machines is never modified, so rollback is a restart.
- OptiQ: set `DEV_MODEL_PATH`/`REVIEW_MODEL_PATH` back to `…-qwen38-27b-8bit` and the two
  `METER_*_MODEL` values to match; restart workers and meter. The 8-bit weights stay on disk.
- `~/ai/venv-mlx-main` can be `rm -rf`'d; nothing else references it.

## Docs updates

- `docs/MODELS.md`: runtime (venv + mlx-lm commit) per endpoint; OptiQ comparison table with
  the eval verdict; Flash-Next as the tracked next upgrade with its benchmark table and blocker.
- `docs/TROUBLESHOOTING.md`: replace "all three open, no released fix" with the current state
  (#1662/#1332 closed on main 2026-08-27, #1845 open, #1872 closed unmerged) and add the
  reproducer.
- `docs/OPERATIONS.md`: the venv override and how to build the pinned venv.
- `scripts/m2-watchdog.sh` comment block referencing the old issue numbers — update the text
  only; behaviour unchanged.

## Risks and edge cases

- **`main` is unreleased.** A pinned commit is reproducible but untested by upstream CI as a
  release. Hence one role at a time, watchdog still armed, stock venv untouched.
- **#1845 means `main` may not fix the M2 workers at all.** The plan treats that as a finding.
  The Orchestrator's failure mode (long prompts) is the more likely beneficiary.
- **`main` changes Qwen3.6 norm sanitization (#1623).** Could shift Orchestrator outputs
  either way — that is why A6 runs the eval before switching M1.
- **`mlx` version drift.** The trial venv will carry mlx ≥ 0.32; the mtp-venv already runs
  0.32.1 on both machines without trouble, but `iogpu` behaviour under a newer mlx should be
  watched during the soak (`memory_pressure`).
- **OptiQ is a third-party quantization recipe.** It loads on stock mlx-lm, but the calibration
  mix is theirs; the eval is the only trustworthy signal. 18 cases is a small set — the
  McNemar output in the report says whether a difference is real.
- **Reproducer prompt.** `enable_thinking: false` keeps the output long and deterministic; the
  leak is per generated token so thinking on/off does not matter for the crash, only for the
  budget arithmetic.
- **Port 8009** must be free on both machines (8004 MTP, 8005 GLM, 8006 VLM, 8010 enrich are
  taken). Check with `lsof -i :8009` first.
- **Do not run A2/A3 while the reviewer is mid-review**: the 27B is memory-bandwidth-bound and a
  second copy halves both servers' tok/s for the duration.
