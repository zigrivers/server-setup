# Speculative Decoding (dense workers) — Design Spec (F6)

**Status:** APPROVED for build (via /goal). Feature 6 of 6. Implementation home: **server-setup**.
mlx_lm.server supports `--draft-model`/`--num-draft-tokens`; with a compatible small draft, dense
models can decode ~2× faster (the draft proposes tokens, the target verifies a batch at once).
**Not for the MoE orchestrator** (known to regress on MoE) — dense developer/reviewer only.

## Goal
Prove speculative decoding gives a real throughput win on our hardware/mlx version, wire it into the
worker start scripts (env-gated, **off by default**), and document how to enable it on the M2 workers
safely — without forcing a disruptive reload of the manually-managed M2 workers in v1.

## The risk that shapes the design
- The M2 workers are **manually managed (no launchd autostart)** and are **Qwen3.5** arch
  (`Qwen3_5ForConditionalGeneration`). Spec decoding requires the **draft to share the target's
  tokenizer/vocab**, and the research found **Qwen3 spec-decode regressions** (mlx-lm #846) — so a
  draft for the real workers is *uncertain* and a bad restart could leave a worker down.
- Therefore v1 **proves the mechanism on M1** with a known-compatible Qwen2.5 pair (same tokenizer),
  measures the speedup, and ships the **env-gated flag + a deployment guide** for M2 — it does **not**
  force-enable spec decoding on the live M2 workers (that's an opt-in, measured step the user runs
  when ready, mirroring F2's M2 deferral).

## Approach
1. **Benchmark** `scripts/bench-spec-decode.py <target> <draft>`: `mlx_lm.stream_generate` with and
   without `draft_model`, on the same prompt; report tok/s each and the speedup, plus the **acceptance
   rate** if exposed. Pure timing; no server needed.
2. **Prove on M1** with `mlx-community/Qwen2.5-7B-Instruct-4bit` (target) + `Qwen2.5-0.5B-Instruct-4bit`
   (draft) — same Qwen2.5 tokenizer, both small, fit M1's 175GB free. Expect a measurable speedup.
3. **Wire the worker scripts**: `start-developer.sh` / `start-reviewer.sh` add
   `${DRAFT_MODEL:+--draft-model "$DRAFT_MODEL" --num-draft-tokens "${NUM_DRAFT_TOKENS:-3}"}` — i.e.
   **only added when `DRAFT_MODEL` is set** (default off → zero behavior change).
4. **Docs** `docs/speculative-decoding.md`: the mechanism, the M1 proof numbers, how to enable on a
   worker (set `DRAFT_MODEL`, restart that ONE worker, measure acceptance + tok/s, keep only if it
   wins), the **MoE-exclusion**, the **Qwen3 caveat**, the **shared-tokenizer requirement**, and the
   **no-batching** constraint.

## Files
| File | Change |
|---|---|
| `scripts/bench-spec-decode.py` (new) | tok/s with vs without a draft model |
| `scripts/start-developer.sh` / `start-reviewer.sh` | env-gated `--draft-model`/`--num-draft-tokens` |
| `docs/speculative-decoding.md` (new) | mechanism, proof, M2 enable guide + caveats |

## Error handling / safety
- Draft tokenizer mismatch → mlx errors at load; the env-gated flag means this only happens when the
  user opts in and restarts a worker (documented to do one worker at a time + verify).
- `DRAFT_MODEL` unset → scripts behave exactly as today (no risk to the running workers).
- Spec decoding + batching are mutually exclusive in mlx_lm — documented.

## Test plan
- `bash -n` the edited worker scripts; confirm `DRAFT_MODEL` unset adds no flags.
- M1 benchmark: tok/s_with_draft vs tok/s_without on the Qwen2.5 pair → report the speedup (the proof).
- (M2 live enablement is the documented opt-in step, not run in v1.)

## Risks
- **Speedup is workload/acceptance-dependent** — drafting helps most when the draft's proposals are
  often accepted (similar model family). The benchmark measures the real number; we don't over-claim.
- **Qwen3.5 workers** may not have a compatible/known-good small draft and may hit the Qwen3
  regression — hence the M1 proof + documented, measured, one-worker-at-a-time M2 rollout.
- **Memory** — a resident draft adds its size (~1GB for 0.5B); negligible on M2.
