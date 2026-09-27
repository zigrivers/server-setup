# 2026-09-27 — Stop the orchestrator's Metal-buffer crash (#1845) with a launch shim

## Goal

Stop `127.0.0.1:8001` dying with `[metal::malloc] Resource limit (499000) exceeded` under
sustained concurrent load, without changing the model, the runtime version, or any answer it
gives.

## Non-goals

- M2 workers (`:8002`/`:8003`). Same bug, same fix would apply; do it as a follow-up once M1 has
  run clean for a week.
- No `pip install` or upgrade in `~/ai/local-ai-stack/.venv` — mlx-lm 0.31.3 / mlx 0.31.2 stay.
- No change to the watchdog, the meter, ports, prompt-cache settings, or the model.

## Current system and evidence (2026-09-27)

`com.localai.orchestrator` → `scripts/start-orchestrator.sh` → `exec mlx_lm.server`
(mlx-lm 0.31.3, mlx 0.31.2), model `orchestrator-qwen36-35b-a3b-heretic-mixed9`
(`qwen3_5_moe`, 40 layers, 30 linear-attention).

- 16 crashes 07:23–13:54 today, every ~27 min, during primary-intel-history's 32k-item Phase 8
  enrichment run (8 concurrent clients, short completions). The watchdog restarted each one;
  every request in the ~2 min gap failed (3,925 items).
- Traceback: `GenerationBatch._step` → `mx.async_eval` — the #1845 site. `ArraysCache.advance()`
  does `left_padding -= N` lazily each decode step and nothing evaluates it, so each linear layer
  grows a graph one node per step.
- Why short completions still crash: the chain lives on the **batch's** cache, which lives as long
  as the batch is non-empty. With 8 clients the batch never drains, so steps accumulate across
  requests: 499000 / (30 − 1) ≈ 17.2k decode steps, ≈ 27 min at this load. TROUBLESHOOTING.md
  describes the single-long-completion case; this is the same leak reached by concurrency.
- Reproduced on this venv with the tiny random-weight `qwen3_next` script from #1845 (no
  downloads): unpatched **crashed at 14,214 tokens** (predicted 14,257); with the patch below it
  **ran 20,000 tokens clean**; greedy output **identical** (SHA-256 of the first 4,000 tokens
  `1417ce613e2b576e` in both).

## Proposed change

The root-cause fix from #1845's body (never merged; #1780/#1784/#1872 — periodic-eval
workarounds — were declined): `advance()` adds `N` to a Python int, and the `left_padding` /
`lengths` properties fold it in on read. No per-step graph, same values.

Applied by a launcher instead of editing site-packages, so the venv stays pristine and the
rollback is one line:

- `scripts/mlx_server_1845.py` — patches `mlx_lm.models.cache.ArraysCache`, then calls
  `mlx_lm.server.main()` with the same argv. Guard: patch only when the installed
  `ArraysCache.advance` source is the known leaking body; otherwise log one line and run
  unpatched (a future mlx-lm that fixes or reshapes it must not be double-patched).
- `scripts/start-orchestrator.sh` — `exec python "$SCRIPT_DIR/mlx_server_1845.py" …` in place of
  `exec mlx_lm.server …`; arguments unchanged.

## Files expected to change

- `scripts/mlx_server_1845.py` (new, ~50 lines)
- `scripts/start-orchestrator.sh` (one line)
- `tests/test_mlx_server_1845.py` (new)
- `docs/TROUBLESHOOTING.md`, `docs/MODELS.md` (leak section: M1 now runs the shim; the
  concurrency route to the crash)

## Tasks

1. Test first: `tests/test_mlx_server_1845.py` (skips when mlx is not importable), run with the
   serving venv's python:
   - after `advance()` ×1,000 on a patched cache, `left_padding` and `lengths` equal the unpatched
     values, and the stored array object was not replaced per step (no graph growth);
   - `filter`, `extend`, `make_mask`, `finalize` give identical results patched vs unpatched;
   - the guard leaves an unrecognised `advance` untouched.
   Confirm the first test fails before the shim exists.
2. Write `scripts/mlx_server_1845.py`; tests pass.
3. Change the `exec` line in `start-orchestrator.sh`.
4. Deploy: `launchctl kickstart -k "gui/$(id -u)/com.localai.orchestrator"` (the same restart the
   watchdog does ~every 27 min today). Confirm the startup line shows the patch applied.
5. `scripts/smoke-test-endpoints.sh`.
6. Docs.

## Acceptance criteria

- Tests pass; tiny-model repro result above recorded in TROUBLESHOOTING.md.
- Orchestrator log shows the shim's "patched" line at startup.
- Under the running enrichment load (8 concurrent clients), **no `Resource limit` line for 2
  hours** — at least 4× the current mean time between crashes.
- Smoke test passes; a fixed prompt at temperature 0 returns the same text before and after.

## Test plan

Unit tests above; the #1845 tiny-model repro patched vs unpatched (already run, results above);
live soak per acceptance; `grep -c "Resource limit" ~/ai/logs/orchestrator.log` before/after.

## Rollback

Revert the `exec` line (or `git revert`), then
`launchctl kickstart -k "gui/$(id -u)/com.localai.orchestrator"`. No venv or model change to undo.

## Risks and edge cases

- **Patching private internals.** Mitigated by the source-match guard and by leaving site-packages
  untouched.
- **Code that reads the fields another way.** In 0.31.3 every access to `left_padding` / `lengths`
  (`filter`, `extend`, `merge`, `make_mask`, `batch_size`, `generate._make_cache`) is plain
  attribute access, which goes through the properties. No `ArraysCache` subclass overrides
  `advance`.
- **Prompt-cache copies** carry the private attributes with them; a copy folds pending steps on
  first read like the original.
- **Restart** drops in-flight requests for ~1–2 min. Clients using `post_waiting` (Phase 8) ride
  through it.
