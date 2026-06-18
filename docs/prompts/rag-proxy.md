# RAG Proxy + Ingest-a-Project Prompt

A reusable prompt for a fresh context window: build a local RAG proxy (transparent, per-project,
default-on-with-auto-skip) + a one-command project ingester, then set up the ~/Developer projects on
it. Self-contained — embeds the stack context and the operational lessons learned. Paste the block.

---

```text
Build a local RAG proxy + a one-command "ingest a project" helper, then set up eight of my
projects on it. Follow the established workflow: brainstorm a short spec → get a multi-model
review from the local developer (9002) + reviewer (9003) models and fix findings → write an
implementation plan → build it TDD → verify live → ship (commit + push). Measure with the eval
harness; don't assume RAG helps — prove it.

## System context (read/verify before building — don't assume)
Two-Mac local AI stack, fully offline, OpenAI-compatible (mlx_lm.server):
- M1 orchestrator 127.0.0.1:8001 (BF16 35B MoE). M2 developer 10.10.10.2:8002 + reviewer
  10.10.10.2:8003 (dense 27B). A logging "meter" proxy fronts them on 9001/9002/9003 (+ ingest
  9100), binding 127.0.0.1 (+ bridge 10.10.10.1). Dashboard (Next.js) on 3111.
- Canonical scripts live in ~/Developer/server-setup/scripts; ~/ai/local-ai-stack/scripts are now
  SYMLINKS to them (single source of truth) and the launchd plists run that path. The stack venv is
  ~/ai/local-ai-stack/.venv (uv-managed — NO pip; install with
  `uv pip install --python ~/ai/local-ai-stack/.venv/bin/python <pkg>`).

## What already exists (reuse it — don't rebuild)
- A conservative RAG toolkit in server-setup/scripts: `rag_lib.py` (embed via mlx-embeddings
  `mlx-community/bge-small-en-v1.5-bf16`, 384-dim, L2-normalized; block-aware `chunk`;
  `ensure_collection`; `delete_path` for freshness; `retrieve` top-k 4 + score gate; `build_rag_prompt`
  = best-chunk-last + return query unchanged when nothing passes the gate; stable `point_id`).
  Plus `rag-ingest.py`, `rag-query.py`, `rag-retrieve.py` (prints JSON {augmented,n_hits,hits}),
  `test-rag.py`, `docs/rag.md`. Env knobs: COLLECTION, QDRANT_URL (http://127.0.0.1:6333),
  RAG_TOP_K (4), RAG_MIN_SCORE (0.55), RAG_EMBED_MODEL.
- Qdrant runs in Docker (container `qdrant-local`, ports 6333/6334, volume ~/ai/qdrant-storage).
- Deps already in the venv: qdrant-client 1.18.0, mlx-embeddings 0.1.0, outlines 1.3.0, jsonschema.
- A measured fact: on stack-knowledge questions RAG beat no-RAG 6W/0L/2T (p=0.031) at ~+2.3s/query;
  off-topic queries retrieve nothing (gate). So RAG should be selective, not blanket.

## Hard-won operational constraints (respect these)
- PORT COLLISIONS ARE REAL. nibble's Docker uses 18001-18003; the stack uses 8001-8003/9001-9003/
  9100; Qdrant 6333/6334; dashboard 3111. Pick a FREE port for the proxy (e.g. 9200) and bind it to
  127.0.0.1 (+ bridge 10.10.10.1 if M2 clients need it). Use the hardened pre-flight pattern from
  start-orchestrator.sh (abort only if OUR server already answers, exit 0 — never a bare lsof).
- FAIL-OPEN like the meter: if Qdrant/embedder/retrieval fails or times out, forward the request
  UNCHANGED. Retrieval must never break serving.
- Privacy/local-only; everything stays on the machine.

## Part 1 — The RAG proxy
A standalone, OpenAI-compatible proxy (Python, in server-setup, reusing rag_lib directly — avoids
shelling out on the hot path) that sits in front of a target upstream and transparently grounds
chat completions:
- `POST /v1/chat/completions` (and pass through `/v1/models`, etc.): take the last user message,
  retrieve from the request's collection, and if hits pass the gate, replace the user content with
  `build_rag_prompt(...)`; then forward to the upstream and stream the response back unchanged.
- **Per-project collection by api-key** (the "point a project at it" mechanism): map the request's
  `Authorization: Bearer <key>` (and/or an `x-rag-collection` header) to a Qdrant collection. **If no
  collection exists for that key, pass through with NO retrieval** — so ALL stack traffic can safely
  route through this proxy and only RAG-enabled projects get augmented (this resolves the
  default-on-vs-opt-in question: default-on proxy, auto-skip when there's no collection or nothing
  clears the gate).
- Upstream is configurable (`UPSTREAM_BASE_URL`, default the meter 9002 or the orchestrator 9001 —
  decide and justify); preserve the `model` field and all other params; support streaming.
- A response header or log line noting whether retrieval fired + how many chunks (observability),
  so it shows up in the dashboard/telemetry if routed through the meter.
- launchd LaunchAgent so it autostarts/survives reboot, with the hardened pre-flight + a real
  health check, logs split stdout/stderr.

## Part 2 — One-command "ingest a project" helper
`scripts/rag-add-project.sh <project-path-or-name>` (resolves under ~/Developer) that:
- Ingests the project's docs + code into a collection named after the project (e.g. `peptides`).
- Walks the right extensions (.md .txt .ts .tsx .js .jsx .py .sh .json .yaml/.yml — confirm) and
  **excludes** node_modules, .git, dist, build, .next, .turbo, coverage, vendor, *.lock, binaries,
  and anything in .gitignore if feasible. Projects are large — this matters.
- Re-running re-ingests with freshness (delete old chunks per path; stable ids).
- Prints a per-collection score-calibration hint (since the gate is corpus-dependent — show the
  score spread for a relevant vs an off-topic probe so the right RAG_MIN_SCORE can be set per
  collection, stored in a small per-collection config).

## Part 3 — Set up my projects
Ingest these from ~/Developer, each into its own collection:
peptides, nibble, my-mordor, sona, rumble, cortex, scaffold, surface.
Then verify retrieval works on each (a query that should hit its docs returns relevant chunks above
the gate; an off-topic query returns nothing).

## Part 4 — Prove it (don't assume)
For 1–2 representative projects, build a small stack/project-knowledge eval set and run the eval
harness's RAG arm (baseline vs rag) → report the McNemar verdict + the latency cost, the same way
we did for server-setup. Tell me where RAG clearly helps and where it's not worth it.

## Output / acceptance
- The proxy is running on a free port, fail-open, per-key collection routing, streaming works,
  autostarts via launchd; pointing a project's base URL + api-key at it transparently grounds
  answers for projects that have a collection and is a no-op for those that don't.
- `rag-add-project.sh` ingests a ~/Developer project (code+docs, exclusions) in one command, with
  freshness + a calibration hint.
- All eight projects ingested + retrieval-verified; at least one measured A/B.
- Docs: how to point a project at the proxy, how to add/refresh a project, how to tune its gate,
  and how to turn RAG off for a project (drop its collection).
- Specs/plans committed; code committed + pushed. Honest about what's v1 vs deferred (e.g. a
  persistent embedding endpoint, re-rank, auto-reindex/file-watching).

Be honest about cost/latency and failure modes; preserve fail-open and the single-source-of-truth
scripts; pick ports that don't collide; and measure before claiming RAG helps for a given project.
```
