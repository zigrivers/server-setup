# Prompt/KV Caching (F2) — Implementation Plan

> Small, ops-focused. Edit the mlx_lm start scripts + add a benchmark; verify live; ship.

### Task 1: Add explicit, bounded cache flags to the start scripts
- [ ] `scripts/start-orchestrator.sh`: before the log redirect, add
      `--prompt-cache-size "${PROMPT_CACHE_SIZE:-10}"` and
      `--prompt-cache-bytes "${PROMPT_CACHE_BYTES:-8GB}"`.
- [ ] `scripts/start-developer.sh` and `scripts/start-reviewer.sh`: same, worker default `12GB`.
- [ ] `bash -n` all three.

### Task 2: Benchmark `scripts/bench-prompt-cache.sh <baseUrl>`
- [ ] Build a byte-identical ~1.5k-token prompt; send twice with `stream:true`, measure TTFT each
      time (curl write-out / first-byte timing); print cold, warm, speedup.
- [ ] Then send 3 distinct long prefixes and re-send the first; confirm HTTP 200 throughout (byte-cap
      stability). Hint to check the server cache log if warm ≥ cold.
- [ ] `bash -n`.

### Task 3: Docs
- [ ] Short prefix-sharing note (identical leading tokens + same model = cache hit; per-request system
      prompt variation defeats it — bridge to F3) + how to read the `Prompt Cache:` log line. Add to a
      README/docs note and reference `PROMPT_CACHE_SIZE`/`PROMPT_CACHE_BYTES`.

### Task 4: Deploy + verify live
- [ ] Restart the orchestrator (M1) with the flags; smoke-test it serves; confirm the cache log line.
- [ ] `bench-prompt-cache.sh http://127.0.0.1:8001/v1` → warm TTFT < cold TTFT (the proof).
- [ ] Copy updated `start-developer.sh`/`start-reviewer.sh` to M2; restart workers; smoke-test 8002/8003;
      bench one worker.
- [ ] Confirm M1 memory pressure didn't regress (Hardware page).

### Task 5: Ship
- [ ] Commit + push server-setup; merge to main.

## Acceptance
- All three servers launch with explicit, byte-bounded prompt caches; the benchmark shows a real
  warm-vs-cold TTFT win on at least the orchestrator; servers stay healthy; docs explain prefix-sharing.
