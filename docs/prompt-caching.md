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

## Operational notes (the two issues below are now RESOLVED — kept for history)
- **Port collision with the `nibble` project — RESOLVED.** `nibble`'s Docker containers used to
  publish `0.0.0.0:8001/8002/8003` (the AI stack's ports), which false-positived the start scripts'
  old `lsof` pre-flight and **crash-looped** the orchestrator on restart. **Fixed two ways:** (1)
  `nibble` was moved to host ports **18001/18002/18003**; (2) the pre-flight was hardened to abort
  only if *our own* mlx server already answers `/v1/models` (exit 0, so "already running" isn't a
  crash) — so the stack now coexists with any future port squatter.
- **Diverged script copies — RESOLVED.** The launchd agents run `~/ai/local-ai-stack/scripts/*.sh`,
  which were *separate copies* from the canonical `~/Developer/server-setup/scripts/*.sh`. Those
  copies are now **symlinks** to the server-setup originals, so there is **one source of truth**:
  editing `server-setup/scripts/` takes effect on the next restart with no manual deploy.
  Verified: the orchestrator restarts cleanly from the canonical script via the symlink.
  (M2's worker copies are still deployed by `scp` since server-setup isn't checked out on M2 — a
  future `com.localai.workers` LaunchAgent + a server-setup checkout on M2 would close that gap.)
- **M2 workers are not under launchd.** Only `com.localai.collector.m2` is a LaunchAgent on M2;
  the developer/reviewer servers run manually (no autostart). The cache flags + hardened pre-flight
  are deployed to M2's scripts and apply on the **next** worker restart/reboot — the currently
  running workers were left untouched to avoid an unnecessary model reload. **Longer-term: add a
  `com.localai.workers` LaunchAgent on M2 so the workers autostart + survive reboots.**
