# Speculative decoding (dense workers)

A small **draft** model proposes several tokens; the **target** verifies them in one batched pass.
When the draft's guesses are accepted often, the target generates the same text in fewer forward
passes → faster. mlx_lm.server supports it via `--draft-model` / `--num-draft-tokens`.

## It is NOT a free win — measure first
**Speculative decoding only helps when the target is slow per-token (memory-bound) AND the draft is
accepted often.** On a *fast* target it can be **slower** (the draft overhead isn't recovered).

Measured on this stack (M1) with `scripts/bench-spec-decode.py`:
```
target Qwen2.5-7B-Instruct-4bit + draft Qwen2.5-0.5B-Instruct-4bit (num_draft_tokens=3)
baseline:    127.8 tok/s
speculative: 114.2 tok/s   -> 0.89x  (SLOWER — the 7B is already fast/bandwidth-bound)
```
So: a fast 7B got **worse**. The win the research reports (~2×) is for **slow dense models** (our
27B workers run ~10 tok/s) with a well-matched draft. **Always benchmark the specific target+draft
pair before enabling.**

## Where it's wired (off by default)
`start-developer.sh` / `start-reviewer.sh` add `--draft-model`/`--num-draft-tokens` **only when
`DRAFT_MODEL` is set** — default behavior is unchanged. The **MoE orchestrator is excluded** (spec
decoding is known to regress on MoE).

## Enabling on a worker (opt-in, one at a time, measured)
1. **Pick a draft that shares the target's tokenizer/vocab** (hard requirement — mlx errors on load
   otherwise). The workers are **Qwen3.5** (`Qwen3_5ForConditionalGeneration`); use a small Qwen3.5
   model with the *same* tokenizer. **Verify it loads** with the target first.
2. **Benchmark it** on the real target before committing:
   `bench-spec-decode.py <target-path> <draft-path> 3 256` — keep only if it's clearly >1.0×.
   Tune `num_draft_tokens` (2–5): a weaker draft wants fewer.
3. Set `DRAFT_MODEL=<draft-path>` (and optional `NUM_DRAFT_TOKENS`) in the worker's environment and
   restart **that one worker**; confirm it serves before doing the other. (M2 workers are manually
   managed with no autostart — restart carefully.)
4. Watch tok/s on the dashboard; revert (unset `DRAFT_MODEL`, restart) if it didn't help.

## Caveats
- **Qwen3 regression**: mlx-lm has reported spec-decode issues on Qwen3 (#846) — test thoroughly.
- **No batching**: spec decoding and request batching are mutually exclusive in mlx_lm.
- **Benchmark vs server**: `bench-spec-decode.py` uses `stream_generate` (the same decode core the
  server uses); absolute tok/s differ from server-under-load but the *relative* speedup is the signal.
- **Memory**: the draft is held resident (~1GB for a 0.5B-4bit; more for a larger/less-quantized draft).
