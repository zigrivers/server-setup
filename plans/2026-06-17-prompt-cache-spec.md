# Prompt / KV Caching — Design Spec (F2)

**Status:** APPROVED for build (via /goal). Feature 2 of 6. Implementation home: **server-setup**
(the mlx_lm start scripts), not the dashboard.

## Goal
Make mlx_lm's prompt/prefix KV cache **explicit, bounded, and verified** on all three model servers,
so repeated shared prefixes (system prompts, multi-turn context) skip re-prefill — a latency win on
time-to-first-token — **without** the cache silently growing and adding memory pressure. Prove the
win with a benchmark.

## Current reality (grounded, not assumed)
- mlx_lm **0.31.3** on M1 and M2; `server.py` already instantiates `LRUPromptCache` →
  **automatic prefix caching is ON by default.**
- The server exposes `--prompt-cache-size` (max distinct KV caches, **default 10**) and
  `--prompt-cache-bytes` (**default None → unbounded by bytes**).
- The start scripts (`scripts/start-orchestrator.sh`, `start-developer.sh`, `start-reviewer.sh`,
  via `start-worker-models.sh` on M2) pass **neither** flag → running on defaults.

**So the latency benefit is already partly delivered.** The real, honest deliverable of F2:
1. **Bound the bytes** (`--prompt-cache-bytes`) so 10 cached long-prompt KV sequences on the BF16
   orchestrator can't quietly contribute to memory pressure — the genuine safety improvement.
2. **Make it explicit + env-configurable** in the start scripts (so it's visible and tunable, not
   an invisible default).
3. **Benchmark** the cold-vs-warm TTFT to prove the win on our hardware.
4. **Document** how to structure shared prefixes to benefit (ties to F3's frozen system prompts).

## Non-goals
- Not building a cache (mlx_lm has it). Not the disk `cache_prompt` workflow in v1 (the in-server
  prefix cache is the free win; disk pre-warm can come with F3's big shared prompt).
- No dashboard code change in v1 (a future nice-to-have: surface "Prompt Cache: N seq, X GB" from the
  server logs on the Hardware page).
- Not touching the meter (the cache is per-upstream-server, transparent to the proxy).

## Approach
1. **Start scripts** — add two env-driven flags to each `mlx_lm.server` exec:
   - `--prompt-cache-size "${PROMPT_CACHE_SIZE:-10}"`
   - `--prompt-cache-bytes "${PROMPT_CACHE_BYTES:-<default>}"` where the default is **machine-aware**:
     orchestrator (BF16 35B, M1) gets a tighter cap (it shares M1 with the meter/dashboard);
     dense workers (M2) can hold more. Concrete defaults: orchestrator **8GB**, workers **12GB**
     each (overridable via env). These are caps, not allocations — the cache only grows as distinct
     prefixes arrive.
2. **Benchmark** `scripts/bench-prompt-cache.sh <baseUrl>`: send a long (~1–2k token) prompt **twice**
   with `stream:true`, measure **time-to-first-token** each time; the second call should hit the
   prefix cache and show markedly lower TTFT. Print cold TTFT, warm TTFT, and the speedup. Uses only
   `curl` + a tiny TTFT timer (no deps).
3. **Verify** the servers log `Prompt Cache: N sequences, X GB` after a couple of requests (the cache
   is working) and that bounding bytes doesn't break serving.
4. **Docs** — a short note in the repo on prefix-sharing: identical leading tokens (same system
   prompt verbatim, same model) are what the cache keys on; varying the system prompt per request
   defeats it. This is the bridge to F3.

## Files
| File | Change |
|---|---|
| `scripts/start-orchestrator.sh` | add `--prompt-cache-size`/`--prompt-cache-bytes` (env, orch default 8GB) |
| `scripts/start-developer.sh` | same (worker default 12GB) |
| `scripts/start-reviewer.sh` | same (worker default 12GB) |
| `scripts/bench-prompt-cache.sh` (new) | cold-vs-warm TTFT benchmark for one endpoint |
| `docs/` or the HTML guide | short prefix-sharing note + how to read the cache log |
| `configs/env.machine1.example` (if present) | document `PROMPT_CACHE_SIZE` / `PROMPT_CACHE_BYTES` |

## Error handling / safety
- Flags are additive and env-overridable; if a value is invalid mlx_lm errors loudly at startup
  (caught immediately on restart, before we trust it). Keep the old behavior reachable by leaving the
  env unset only if we keep the same defaults — but we deliberately set a bytes cap, which is the point.
- Restarting a server drops its in-memory cache (expected; it re-warms on use).
- M2 scripts must be redeployed to M2 and the workers restarted for the change to take effect.

## Test plan
- `bash -n` all edited scripts.
- Restart the orchestrator with the flags; confirm it serves (smoke test) and logs the cache line.
- `bench-prompt-cache.sh` against the orchestrator: warm TTFT < cold TTFT (the proof). Repeat for a
  worker.
- Confirm memory pressure on M1 doesn't regress vs the unbounded default (the dashboard Hardware page).

## Rollback
- Revert the start-script edits and restart; the server returns to default (size 10, unbounded bytes).

## Risks
- **Most of the win may already be delivered by the default** — F2's measurable delta is the
  *byte-bounding* (safety) plus making it explicit/measured. The benchmark will quantify the actual
  TTFT win so we don't over-claim.
- **Prefix-sharing depends on identical leading tokens** — without F3's frozen system prompts, cross-
  client hits are rare; the cache mainly helps within multi-turn / repeated-prompt bursts. Documented.
- **Byte cap too low** → fewer cache hits; too high → memory pressure. Defaults are conservative and
  env-tunable; the benchmark + Hardware page tell us if we mis-set them.
