# RAG Proxy + Ingest-a-Project — Design Spec

**Status:** DRAFT → multi-model review → plan. Builds on the approved RAG toolkit (F5,
`plans/2026-06-17-rag-spec.md`). Home: **server-setup** (serving tools; Python). Same governing
caveat as F5: *bad retrieval hurts more than none* — so retrieval stays conservative (small top-k,
score gate, no-inject-on-empty) and **we measure before claiming RAG helps for a given project.**

## Goal

Make the conservative RAG toolkit usable *transparently, per project*: a standalone
OpenAI-compatible **proxy** that any client can point its base URL + api-key at, which grounds chat
completions from a per-project Qdrant collection **only when one exists and a hit clears the gate** —
otherwise it is a pure pass-through. Plus a **one-command ingester** that loads a `~/Developer`
project's code+docs into its own collection with sane exclusions, freshness, and a gate-calibration
hint. Then set up eight projects on it and **A/B at least one** with the eval harness.

## Non-goals (v1)

- **No re-rank model, no auto-reindex / file-watching.** Ingest stays a manual one-command step.
- **No new always-on embedding HTTP endpoint as a separate service.** (The proxy process *does* keep
  the embedder resident in-memory as a side benefit — a partial, free win toward the documented
  "persistent embedder" path — but we are not building a standalone `/embeddings` server.)
- **No change to the meter, the dashboard schema, or the workers.** The proxy composes *in front of*
  the existing meter; we add nothing to their codebases.
- **No multi-collection fan-out per request.** One request → at most one collection.
- **No auth/secrets.** Local-only, loopback (+ optional Thunderbolt bridge). The "api-key" is a
  routing label, not a credential.

## Current system summary (verified, not assumed)

- Two-Mac offline stack, OpenAI-compatible (`mlx_lm.server`). M1 orchestrator `127.0.0.1:8001`
  (BF16 35B MoE). M2 developer `10.10.10.2:8002` + reviewer `10.10.10.2:8003` (dense 27B).
- A **meter** proxy (Node/TS, `local-ai-dashboard/src/meter`) binds `127.0.0.1` on **9001→8001**,
  **9002→10.10.10.2:8002**, **9003→10.10.10.2:8003**, ingest **9100** (+bridge `10.10.10.1`). It
  streams SSE through, is fail-open, and logs telemetry to SQLite keyed by the `Authorization:
  Bearer <key>` value (the "client" label), **recording the prompt content it receives**. Dashboard
  (Next.js) reads that DB on `3111`.
- **RAG toolkit** in `server-setup/scripts`: `rag_lib.py` (embed via `mlx-community/bge-small-en-v1.5-bf16`
  384-dim L2-normalized; block-aware `chunk`; `ensure_collection`; `delete_path`; `retrieve(cl, q,
  k, min_score, name=)` — **already takes a per-call collection `name`**; `build_rag_prompt` =
  best-chunk-last + return-query-unchanged-on-empty; stable `point_id`). Plus `rag-ingest.py`,
  `rag-query.py`, `rag-retrieve.py` (prints `{augmented, n_hits, hits}`), `test-rag.py`, `docs/rag.md`.
  Env: `COLLECTION`, `QDRANT_URL` (`http://127.0.0.1:6333`), `RAG_TOP_K`=4, `RAG_MIN_SCORE`=0.55,
  `RAG_EMBED_MODEL`.
- **Qdrant** in Docker (`qdrant-local`, 6333/6334, volume `~/ai/qdrant-storage`); currently one
  collection: `server_setup`.
- **Eval harness** (TS, `local-ai-dashboard/src/eval/run.ts`): a `rag` arm shells out to
  `rag-retrieve.py` (inheriting env, so `COLLECTION=<project>` targets a project), replaces the last
  user message with the augmented prompt, and computes a **McNemar** baseline-vs-rag verdict
  (W/L/T, p-value) + per-arm latency, judged blind by the reviewer (9003).
- **Free port:** 9200 confirmed free. Stack venv `~/ai/local-ai-stack/.venv` (Python 3.12) has
  `qdrant-client`, `mlx-embeddings` (and `httpx`/`starlette`/`uvicorn`, unused here — see decision).

## Key decisions (the prompt asked me to "decide and justify" / "confirm")

1. **Proxy sits in FRONT of the meter; default `UPSTREAM_BASE_URL=http://127.0.0.1:9002/v1`.**
   Chain: `client → rag-proxy:9200 → meter:9002 → worker:8002`. Rationale: the proxy augments the
   prompt *before* the meter, so the meter records the grounded prompt and attributes it by api-key
   (= collection name) — **observability is automatic, no meter change**. 9002 (developer/coding
   model) is the natural default target for project Q&A; it is one env var to repoint at the
   orchestrator via the meter (`http://127.0.0.1:9001/v1`). Justified and configurable.

2. **Collection routing = `x-rag-collection` header if present, else the Bearer api-key value.**
   Pointing a project at RAG is then just "set its api-key to the collection name" (e.g. `peptides`).
   **If that collection does not exist in Qdrant → pass through with NO retrieval.** This makes the
   whole thing default-on-with-auto-skip: *all* stack traffic can safely route through 9200; only
   keys that match a real collection get grounded. **Turning RAG off for a project = drop its
   collection** (an acceptance criterion, satisfied for free). Existence is checked against a cached
   set of Qdrant collection names with a **short TTL (default 10 s)**; *(revised after review)* a
   request whose key is **not** in the cached set triggers a **forced refresh before** concluding
   pass-through, so a just-ingested collection is visible immediately (no stale-negative window);
   dropping a collection turns RAG off within ≤TTL. On a refresh error the **last known-good set is
   retained** (a Qdrant blip must not silently disable RAG for every project). The Bearer value is a
   routing label, not a credential; `x-rag-collection` is the explicit override and collisions
   (a real token equal to a project name) are documented.

3. **Stdlib `ThreadingHTTPServer` for the listener; `httpx` (`stream=True`) for the upstream call.**
   *(Revised after review — see below.)* The server side is stdlib (small/composable, no new
   server framework). The upstream client is **httpx streaming**, not `urllib.request`, because
   `urllib` buffers the whole body to compute `Content-Length`, which would block SSE until the
   full generation finished. Streaming responses are sent to the client with `Connection: close`
   (the body is delimited by EOF — no manual chunked framing, no Content-Length); non-streaming
   responses are forwarded with a real `Content-Length`. `httpx` is already in the stack venv.
   MLX embedding is serialized behind a lock (single user, low concurrency).

4. **Per-collection gate config** stored as JSON under `RAG_CONFIG_DIR`
   (default `~/ai/local-ai-stack/rag-collections/<name>.json` → `{"min_score": float, "top_k": int}`).
   The ingester writes a calibrated `min_score`; **both** the proxy and `rag-retrieve.py` read it via
   a new `rag_lib.collection_config(name)` helper, so the proxy and the eval arm gate identically.
   Absent file → library defaults (0.55 / 4). Kept out of the repo (machine/data-specific), beside
   the venv where it is discoverable.

5. **Ingest file list comes from `git ls-files` when the project is a git repo** (all 8 are), which
   respects `.gitignore` and only sees real tracked source — then filtered by extension + exclusions
   + a size cap. Non-git fallback: `find` with directory prunes. Extensions (confirmed):
   `.md .txt .ts .tsx .js .jsx .py .sh .json .yaml .yml`. Excludes: `node_modules .git dist build
   .next .turbo coverage vendor .venv __pycache__`, `*.lock`, `*.min.*`, files > `RAG_MAX_FILE_BYTES`
   (default 200 KB → skips minified/generated blobs), and binaries. A full project re-ingest
   **syncs without downtime** *(revised after review)*: it upserts the current files (per-file
   `delete_path` + stable ids handle changed files), then deletes points whose `path` is no longer
   in the current file set — so deleted files leave no stale chunks **and the collection is never
   empty mid-refresh** (queries during re-ingest still work).

## Proposed architecture

```
                      ┌────────────────────────────────────────────┐
  any OpenAI client   │  rag-proxy  (scripts/rag-proxy.py, :9200)   │
  base_url=:9200/v1 ──▶  • /healthz  → {"service":"rag-proxy"}      │
  api_key=<collection>│  • /v1/chat/completions:                    │
                      │      key/header → collection                │
                      │      exists? & last-user retrieves a hit    │
                      │      above gate?  → build_rag_prompt()       │
                      │      else: forward body UNCHANGED            │
                      │  • /v1/* (models, embeddings…) → pass-through│
                      │  • fail-open: any RAG error/timeout → unchanged
                      │  • resp headers: x-rag-collection / -applied / -hits
                      └───────────────┬────────────────────────────┘
                                      │  (augmented or original)
                                      ▼
                          meter :9002 ──▶ worker 10.10.10.2:8002
                          (telemetry: records grounded prompt, client=<collection>)
```

### Components (each independently testable)

- **`rag_lib` additions (pure/unit-tested):** `collection_config(name) -> {min_score, top_k}` (reads
  `RAG_CONFIG_DIR`, falls back to defaults; pure given a dir); `collection_exists(cl, name)` (thin
  Qdrant call). No change to existing helpers.
- **`scripts/rag-proxy.py`:** the stdlib server. Request handler split into pure-ish units:
  `pick_collection(headers) -> name|None`, `maybe_augment(body_json, collection) -> (new_body,
  applied, n_hits)` (calls retrieve+build_rag_prompt; returns original on no-collection/no-hit/error),
  and `forward(method, path, headers, body) -> streamed response`. A module-level TTL cache of
  existing collection names. A lock around embedding.
- **`scripts/rag-add-project.sh`:** resolve path under `~/Developer` → collection name → enumerate
  files (git ls-files | filter) → recreate collection → pipe file list into `rag-ingest.py -` →
  calibrate gate (relevant vs off-topic probe scores) → write `RAG_CONFIG_DIR/<name>.json` → print a
  hint.
- **`scripts/rag-ingest.py` extension:** accept `-` to read a newline-delimited file list from stdin
  (keeps walking/exclusion logic in the shell, avoids argv limits); honor `COLLECTION` (already does
  via `rag_lib`) and a `RAG_RECREATE=1` flag to drop+recreate before ingesting.
- **`scripts/rag-retrieve.py` change:** apply `collection_config(COLLECTION)` so eval-arm gating
  matches the proxy.
- **`scripts/start-rag-proxy.sh` + launchd `com.localai.rag-proxy.plist`:** hardened preflight
  (probe `:9200/healthz` for OUR marker, `exit 0` if already answering — never a bare lsof), bind
  `127.0.0.1` (+ `10.10.10.1` if `RAG_PROXY_BRIDGE_HOST` set), logs split stdout/stderr, RunAtLoad +
  KeepAlive (mirrors the meter's LaunchAgent).

## Files expected to change / add

| File | Change |
|---|---|
| `scripts/rag_lib.py` | + `collection_config()`, `collection_exists()` |
| `scripts/rag-proxy.py` | **new** — the stdlib OpenAI-compatible RAG proxy |
| `scripts/rag-add-project.sh` | **new** — one-command project ingester + calibration |
| `scripts/rag-ingest.py` | accept `-` (stdin file list) + `RAG_RECREATE` |
| `scripts/rag-retrieve.py` | honor per-collection config |
| `scripts/start-rag-proxy.sh` | **new** — launcher w/ hardened preflight + health check |
| `configs/launchd/com.localai.rag-proxy.plist(.template)` | **new** — LaunchAgent |
| `scripts/test-rag.py` | + unit tests for `collection_config`, `pick_collection`, `maybe_augment` (mocked) |
| `tests/` | + a proxy integration test against a fake upstream (stdlib) |
| `docs/rag-proxy.md` | **new** — point a project at it / add+refresh / tune gate / turn off |
| `docs/rag.md`, `README.md`, `docs/OPERATIONS.md` | cross-link the proxy |

## Error handling / fail-open (non-negotiable)

*(Fail-open scope tightened after review: only the **retrieval/augment** step is fail-open; genuine
proxy/forward errors are surfaced, never silently swallowed.)*

- **RAG-step failures** (Qdrant down, embedder error, retrieval exception, or retrieval exceeding
  `RAG_TIMEOUT_MS`, **default 5000**) → **forward the request body UNCHANGED**, header
  `x-rag-applied: 0`. Retrieval must never break serving.
- **Proxy/forward failures** (malformed request JSON we must parse, upstream connect/refused) →
  return a clear `502`/`400` (do **not** fake success). Upstream HTTP errors are forwarded verbatim.
- **Collection cache refresh failure** → retain the **last known-good** set (not "no collections"),
  logged. Only a cold start with Qdrant unreachable yields empty → pass-through.
- **Whitelist:** only `POST /v1/chat/completions` is ever augmented. `/v1/models`, `/v1/embeddings`,
  and every other path are transparent pass-through (a test asserts `/v1/embeddings` never retrieves).
- **Body fidelity:** augmentation deserializes the JSON, replaces **only the last user message's
  content**, and re-serializes the **full** object — all other fields (`stream`, `stream_options`,
  `model`, `temperature`, `logprobs`, …) preserved byte-for-meaning.
- **Streaming:** response bytes are pumped through unmodified (only the *request* prompt is ever
  rewritten). On client disconnect (`BrokenPipeError`/closed `wfile`) the upstream stream is closed
  immediately so no thread/connection leaks.
- **Optional per-request upstream override:** `x-rag-upstream: <base-url>` lets a caller target a
  different meter port (e.g. `http://127.0.0.1:9001/v1` for the orchestrator) without a second proxy;
  absent → `UPSTREAM_BASE_URL` default. (Model-aware auto-routing is deferred, documented.)
- **Observability headers** on the client response: `x-rag-collection`, `x-rag-applied` (0/1),
  `x-rag-hits` (N), `x-rag-latency-ms` (time in retrieval). `x-rag-applied` is also set on the
  request forwarded to the meter (harmless; lets a future meter tag RAG vs plain without a schema
  change today).

## Acceptance criteria

- Proxy on `:9200`, loopback-bound, autostarts via launchd, `/healthz` returns the marker.
- A request with `Authorization: Bearer peptides` (collection exists) gets a grounded prompt when a
  hit clears the gate; `x-rag-applied: 1`, `x-rag-hits: N`, `x-rag-collection: peptides`.
- A request with an unknown key (no collection) or a gate miss is byte-for-byte pass-through,
  `x-rag-applied: 0`; **all stack traffic can route through 9200 safely.**
- Streaming (`stream: true`) works end-to-end; `model` + other params preserved.
- Killing Qdrant → proxy still serves (unchanged), proving fail-open.
- `rag-add-project.sh peptides` ingests code+docs (exclusions honored) in one command, recreates the
  collection for freshness, and prints a calibration hint + writes the per-collection config.
- All 8 projects ingested + retrieval-verified (relevant query hits above gate; off-topic returns
  nothing).
- ≥1 project A/B'd through the eval harness: McNemar verdict + latency cost reported honestly.
- Telemetry: a proxied grounded request shows the augmented prompt in the dashboard, client=collection.

## Test plan

- **Unit (no model/Qdrant):** `collection_config` (file present/absent, bad JSON → defaults);
  `pick_collection` (header > key > none); `maybe_augment` with a stubbed `retrieve` (hit → augmented
  + applied; empty → unchanged; raises → unchanged).
- **Integration (stdlib fake upstream):** spin a throwaway HTTP server as the "upstream"; point the
  proxy at it; assert (a) unknown key → body forwarded **verbatim incl. all fields** (`temperature`,
  `stream_options`, …), (b) known collection + stubbed hit → forwarded body contains the context block
  **and still carries every original field**, (c) `stream:true` SSE chunks arrive incrementally and
  in order (first chunk before the upstream finishes — proves no buffering), (d) upstream 502 surfaces
  unchanged, (e) `POST /v1/embeddings` with a collection-like key → **no retrieval**, forwarded
  verbatim, (f) a brand-new collection created after startup is seen on the **next** request (forced
  negative refresh).
- **Live smoke:** start proxy → `/healthz`; curl chat with `Bearer server_setup` (exists) vs a junk
  key; `stream:true`; stop Qdrant and confirm pass-through; confirm meter logged the augmented prompt.
- **Per project:** after ingest, a known-relevant query returns ≥1 hit above the gate and a fixed
  off-topic query returns 0.

## Revisions from multi-model review (incorporated)

Reviewed by the local developer (9002) + reviewer (9003) models. Findings folded in:

- **[BLOCKER, both] Streaming via `urllib` buffers for `Content-Length`, breaking SSE.** → upstream
  client is now **httpx `stream=True`**; client responses use `Connection: close` for streams.
- **[BLOCKER, dev] Fail-open was too broad** — could swallow proxy bugs. → only the retrieval step is
  fail-open; parse/forward errors surface as `400`/`502`.
- **[BLOCKER, both] Existence-cache staleness both directions** (fresh ingest invisible / drop lingers).
  → 10 s TTL + forced refresh on negative lookups + keep-last-known on refresh error.
- **[SHOULD, reviewer] Body fidelity** — re-serialize the full request object, replace only the last
  user message.
- **[SHOULD, both] Client-disconnect handling** — close the upstream stream on `BrokenPipeError`.
- **[SHOULD, dev] No-downtime re-ingest** — sync (upsert + delete-vanished-paths) instead of
  drop+recreate.
- **[SHOULD, dev] Lower `RAG_TIMEOUT_MS`** 8000 → 5000.
- **[SHOULD, both] Single-model upstream** — added optional `x-rag-upstream` header; model-aware
  auto-routing explicitly deferred.
- **[SHOULD, dev] Chat-only RAG whitelist** made explicit + a `/v1/embeddings` pass-through test.
- **[NICE, reviewer] `x-rag-latency-ms`** observability header added.
- **[BLOCKER, dev] LAN exposure** — default bind is loopback-only; bridge bind is opt-in and
  documented as trusted-link-only; the "api-key" is explicitly not a credential.

*Not adopted:* meter schema changes for header-level RAG tagging (the meter already records the
augmented prompt content and attributes by key; a `x-rag-applied` request header is forwarded for a
future, zero-cost upgrade) — kept as a non-goal to honor "no change to the meter."

## Rollback plan

- The proxy is **additive and opt-in by base-URL**: nothing routes through 9200 until a client points
  at it. Rollback = `launchctl bootout` the agent and stop the script; the stack is untouched.
- Per project: `rag-add-project.sh` only writes a Qdrant collection + a config JSON. Undo = delete the
  collection (`curl -X DELETE :6333/collections/<name>`) and remove the JSON. Disabling RAG for a
  project is the same delete.
- All code is committed in small steps; `git revert` restores any script.

## Docs updates

- **`docs/rag-proxy.md`** (new): the chain diagram; how to point a project's `base_url`+`api_key` at
  9200; `rag-add-project.sh` usage; reading + tuning the per-collection gate; turning RAG off (drop
  the collection); the launchd lifecycle; honest v1-vs-deferred list.
- Cross-links from `docs/rag.md`, `README.md`, `docs/OPERATIONS.md`.

## Risks & edge cases

- **Latency:** ~+2.3 s/query measured (embed+search) on the hot path *only when a collection matches*;
  pass-through adds ~one Qdrant existence check (cached). Documented; the A/B is the real safeguard.
- **Distractors hurt:** mitigated by the score gate + no-inject-on-empty + per-collection calibration.
- **MLX thread-safety:** embedding serialized behind a lock; acceptable for single-user.
- **Stale chunks:** whole-project re-ingest recreates the collection, so deletions don't linger.
- **Big repos** (scaffold 3.4k files): size cap + exclusions + git ls-files keep ingest bounded; we
  report counts and skips honestly (no silent truncation).
- **Per-key collision:** a project whose name collides with a real api-key would get unexpected
  grounding — names are explicit and local; documented.
- **Honest scope:** v1 = transparent proxy + ingester + measurement. Deferred (documented): standalone
  persistent `/embeddings` service, re-rank, auto-reindex/file-watching, header-level telemetry in the
  meter.
