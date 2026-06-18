# RAG Proxy + Ingest-a-Project — Implementation Plan

Executes `plans/2026-06-17-rag-proxy-spec.md` (multi-model reviewed). TDD throughout: a failing test
or a live check precedes each claim of "done". Commit at each milestone; push at the end of each part.

## Goal / non-goals

See the spec. In short: a transparent, per-project, default-on-with-auto-skip OpenAI-compatible RAG
proxy on `:9200` in front of the meter, a one-command project ingester with calibration, eight
projects set up, and ≥1 measured A/B. Non-goals: re-rank, auto-reindex, a standalone embeddings
service, meter/dashboard changes.

## Build order (each step: test/red → code/green → verify)

### Step 1 — `rag_lib` helpers (pure, unit-tested)
- **1a** `collection_config(name, config_dir=None) -> {"min_score": float, "top_k": int}`: read
  `${RAG_CONFIG_DIR:-~/ai/local-ai-stack/rag-collections}/<name>.json`; missing/invalid → defaults
  (`DEFAULT_MIN_SCORE`, `DEFAULT_K`). Pure given `config_dir`.
- **1b** `collection_exists(cl, name) -> bool` and `list_collections(cl) -> set[str]` (thin Qdrant
  wrappers; integration-level, not unit-tested).
- **Tests (test-rag.py):** config present / absent / malformed-json → defaults; env override of dir.

### Step 2 — proxy request logic (pure-ish, unit-tested with stubs)
- **2a** `pick_collection(headers) -> str|None`: `x-rag-collection` else Bearer value (strip
  `Bearer `), else None. Empty/whitespace → None.
- **2b** `maybe_augment(body: dict, collection, retrieve_fn) -> (new_body, applied: bool, n_hits, ms)`:
  if collection falsy → `(body, False, 0, 0)`. Else time a `retrieve_fn(collection)`; on exception or
  empty → `(body, False, 0, ms)`; on hits → copy body, replace **last user message content** with
  `build_rag_prompt(orig, hits)`, return `(new_body, True, len(hits), ms)`. Never mutates input.
- **Tests:** header>key>none precedence; augment with stubbed retrieve (hit → applied + context in
  last user msg + all other fields preserved; empty → unchanged; raises → unchanged, applied False).

### Step 3 — `scripts/rag-proxy.py` (stdlib server + httpx upstream)
- `ThreadingHTTPServer` bound to `RAG_PROXY_HOST` (default `127.0.0.1`; optional second bind on
  `RAG_PROXY_BRIDGE_HOST`), port `RAG_PROXY_PORT` (9200).
- `do_GET /healthz` → `200 {"service":"rag-proxy","ok":true,"upstream":<url>,"collections":N}`.
- `do_POST` / `do_GET` else → `handle(path)`:
  - read body; if `path == /v1/chat/completions`: parse JSON (parse fail → 400), `pick_collection`,
    refresh-cache-if-key-unknown, `maybe_augment` (guarded by `RAG_TIMEOUT_MS` via a worker thread +
    `future.result(timeout)`; timeout/err → unchanged), re-serialize.
  - forward to `upstream (x-rag-upstream header else UPSTREAM_BASE_URL) + path` with **httpx**:
    streaming if request `stream:true` or upstream `content-type: text/event-stream`.
  - copy upstream status + headers (drop hop-by-hop + content-length for streams); add `x-rag-*`
    headers; set `Connection: close` for streams; stream `iter_raw()` to `wfile`, flush each;
    `BrokenPipeError` → close upstream, return.
  - upstream connect error → 502 JSON.
- Module state: collection-name set + TTL + lock; `embed`/`retrieve` serialized behind a lock.
- Stdlib logging: one line per request `ts kind collection applied n_hits ms status`.

### Step 4 — proxy integration test (`tests/test_rag_proxy.py`)
- Fake upstream = a `ThreadingHTTPServer` in-process that echoes the received body (non-stream) and an
  SSE generator (stream) with a deliberate inter-chunk delay.
- Monkeypatch the proxy's `retrieve` to a stub (no Qdrant/MLX) and its collection set.
- Assert spec test-plan items (a)–(f): verbatim forward incl. all fields; augmented body carries the
  context + all fields; SSE first-chunk-before-finish (no buffering); upstream 502 passthrough;
  `/v1/embeddings` never retrieves; new-collection seen on next request.
- Runs with stack venv; no network beyond loopback.

### Step 5 — ingester
- **5a** `rag-ingest.py`: add `-`/`--stdin` (read newline-delimited paths from stdin); add
  `RAG_RECREATE` is **replaced** by sync — keep `COLLECTION`/stable-id behavior; expose a
  `--sync-paths` mode: after upserting the given files, delete points whose `path` ∉ the given set
  (scroll payloads for distinct paths). Back-compat: dir-walk mode unchanged but extensions broadened.
- **5b** `scripts/rag-add-project.sh <name-or-path>`:
  - resolve under `~/Developer`; `COLLECTION=<basename>`.
  - enumerate: `git -C <proj> ls-files` (fallback `find` with prunes) → filter ext allowlist, drop
    excludes (`node_modules .git dist build .next .turbo coverage vendor .venv __pycache__ *.lock
    *.min.*`), drop files > `RAG_MAX_FILE_BYTES` (200 KB), drop binary (grep -Iq).
  - pipe the absolute paths into `rag-ingest.py --stdin --sync-paths` with `COLLECTION` set.
  - **calibrate:** run a relevant probe (`"<name> project overview architecture"`) and an off-topic
    probe (`"sourdough bread baking temperature"`); print top score for each; suggest
    `min_score = round((rel_top + off_top)/2, 2)` clamped to `[0.45, 0.7]`; write
    `RAG_CONFIG_DIR/<name>.json`. Print the hint + how to override.
  - print counts (files scanned/ingested/skipped) — **no silent truncation**.

### Step 6 — launchd + launcher
- `scripts/start-rag-proxy.sh`: `set -euo pipefail`; activate stack venv; hardened preflight
  (`curl :9200/healthz | grep -q '"service":"rag-proxy"'` → already up, `exit 0`); `exec python
  scripts/rag-proxy.py`; logs → `~/ai/logs/rag-proxy.log`.
- `configs/launchd/com.localai.rag-proxy.plist.template` (mirrors meter agent): RunAtLoad, KeepAlive,
  stdout/stderr split, `__USER__`/`__HOME__` placeholders. Add an installer note (or extend
  `install-launchd-machine1.sh`).

### Step 7 — verify live (spec acceptance)
Start proxy; `/healthz`; chat with `Bearer server_setup` (exists) vs junk key; `stream:true`; stop
Qdrant → still serves; confirm meter logged the augmented prompt + client label.

### Step 8 — ingest + verify 8 projects
`rag-add-project.sh` for peptides, nibble, my-mordor, sona, rumble, cortex, scaffold, surface. Per
project: a relevant query returns ≥1 hit above the gate; a fixed off-topic query returns 0.

### Step 9 — eval A/B (≥1 project)
Build a small per-project eval set (questions answerable from its docs) at
`local-ai-dashboard/eval/eval-config-<name>.json` (arms: baseline + rag). Run with
`COLLECTION=<name> EVAL_CONFIG=... pnpm eval`. Report McNemar W/L/T + p + latency. Honest verdict.

### Step 10 — docs + ship
`docs/rag-proxy.md` (point a project at it / add+refresh / tune gate / turn off / launchd / v1-vs-
deferred). Cross-link `docs/rag.md`, `README.md`, `docs/OPERATIONS.md`. Commit per part; push.

## Acceptance criteria
(Verbatim from the spec's "Acceptance criteria" — all must pass with shown evidence.)

## Test plan
(Per spec "Test plan": unit + stdlib integration + live smoke + per-project retrieval + ≥1 A/B.)

## Rollback plan
Proxy is additive/opt-in by base-URL: `launchctl bootout` + stop script. Per project: delete the
Qdrant collection + its config JSON. All code committed in small steps (`git revert`).

## Risks / edge cases
See spec "Risks & edge cases": latency (~+2.3 s only on a collection match), distractors (gate),
MLX thread-safety (lock), big repos (size cap + exclusions, counts reported), bearer/collection
collision (documented), honest v1 scope.
