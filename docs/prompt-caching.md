# Prompt / prefix KV caching (mlx_lm)

All three model servers (orchestrator, developer, reviewer) run mlx_lm's built-in **prefix KV
cache** — when a new request shares a leading token prefix with a recent one, the server reuses the
cached KV state instead of re-prefilling it, cutting **time-to-first-token (TTFT)**.

## What we set
The start scripts pass two flags (env-tunable):
- `--prompt-cache-size` (env `PROMPT_CACHE_SIZE`, default **10**) — max distinct prefixes held.
- `--prompt-cache-bytes` (env `PROMPT_CACHE_BYTES`, default **8GB** orchestrator / **12GB** workers) —
  a hard **byte cap**. mlx_lm's default is *unbounded* by bytes, which could let 10 long-prompt KV
  caches quietly add memory pressure; the cap prevents that. (`_parse_size` accepts `8GB`, `12GB`,
  or a raw integer — decimal GB, ×1e9.)

## How to benefit (prefix sharing)
The cache keys on **identical leading tokens for the same model**. To get hits:
- Keep the **system prompt byte-identical** across requests (same wording, same order). A system
  prompt that varies per request defeats the cache. This is the bridge to the *frozen per-role
  prompts* work (F3) — once each role has one stable system prompt, every call to that role shares
  the prefix.
- Multi-turn conversations naturally share the growing prefix.

## Verify
- After a couple of requests, the server log shows: `Prompt Cache: N sequences, X GB`.
- Prove the win: `scripts/bench-prompt-cache.sh http://127.0.0.1:8001/v1` sends a byte-identical long
  prompt twice and reports cold vs warm TTFT + the speedup.

## Rollback
Revert the start-script edits **and** unset `PROMPT_CACHE_SIZE` / `PROMPT_CACHE_BYTES` in any env
file, then restart. The server returns to the mlx_lm defaults (size 10, bytes unbounded).
