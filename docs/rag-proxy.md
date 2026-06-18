# RAG Proxy — point a project at local RAG, transparently

A standalone OpenAI-compatible proxy on **`127.0.0.1:9200`** that sits **in front of the meter** and
transparently grounds chat completions from a **per-project Qdrant collection** — but only when one
exists and a retrieved chunk clears the gate. Otherwise it is a pure pass-through. So **all** stack
traffic can safely route through it; only RAG-enabled projects get augmented (default-on with
auto-skip).

```
client (base_url=:9200/v1, api_key=<collection>)
   → rag-proxy :9200   ── augment last user msg iff collection exists & a hit clears the gate
      → meter :9002     ── records the (grounded) prompt for the dashboard
         → worker 10.10.10.2:8002
```

It reuses the conservative RAG toolkit (`rag_lib`, see [`rag.md`](rag.md)): small top-k, a per-collection
score gate, and **never inject context when nothing passes the gate** (bad retrieval hurts more than
none). The proxy keeps the embedder resident in-process, so retrieval is ~fast after the first call.

## Point a project at it

Set the project's OpenAI client to the proxy and use the **collection name as the api-key**:

```bash
export OPENAI_BASE_URL="http://127.0.0.1:9200/v1"
export OPENAI_API_KEY="peptides"        # = the collection name
# or, instead of the api-key, send a header:  x-rag-collection: peptides
```

- If a collection named `peptides` exists → the last user message is grounded from it (when a hit
  clears the gate). Response headers report what happened:
  `x-rag-applied: 1`, `x-rag-hits: N`, `x-rag-collection: peptides`, `x-rag-latency-ms: …`.
- If no such collection exists (or nothing clears the gate) → the request is forwarded **unchanged**
  (`x-rag-applied: 0`). Nothing breaks.

**Target a different model.** The default upstream is the meter's developer port (`9002`). To send a
single request to the orchestrator instead, add a header: `x-rag-upstream: http://127.0.0.1:9001`.
(Permanent change: set `UPSTREAM_BASE_URL` in `start-rag-proxy.sh`.)

## Add or refresh a project

```bash
scripts/rag-add-project.sh <project-name-or-path>     # resolves under ~/Developer
```

What it does:
- Enumerates source files via `git ls-files` (respects `.gitignore`; falls back to `find` for non-git
  dirs), keeping `.md .txt .ts .tsx .js .jsx .py .sh .json .yaml .yml` and **excluding**
  `node_modules .git dist build .next .turbo coverage vendor .venv __pycache__`, lockfiles,
  `*.min.*`, files > `RAG_MAX_FILE_BYTES` (200 KB), and binaries. It prints the counts
  (`scanned/kept/skipped`) — nothing is silently dropped.
- Ingests into a collection named after the project, with **no-downtime sync**: it upserts the
  current files and deletes points for files that have since vanished (the collection is never
  emptied mid-refresh, so live queries keep working). Re-run any time to refresh.
- **Calibrates the gate**: probes the collection with a relevant query and a fixed off-topic query,
  prints both top scores, and writes a suggested `min_score` to the per-collection config.

## Tune a project's gate

Each collection has a config at `~/ai/local-ai-stack/rag-collections/<name>.json`:

```json
{ "min_score": 0.7, "top_k": 4 }
```

- **Raise `min_score`** to be stricter (fewer, more-relevant chunks; more pass-throughs).
- **Lower it** to retrieve more aggressively (risk: distractors).
- Re-calibrate any time: `COLLECTION=<name> ~/ai/local-ai-stack/.venv/bin/python scripts/rag-calibrate.py <name> "a known-relevant question"`.

Both the proxy **and** the eval harness read this file, so what you measure is what you serve.
(Env override: `RAG_CONFIG_DIR` relocates the directory.)

## Turn RAG off for a project

Drop its collection — the proxy reverts that key to pure pass-through within the cache TTL (≤10 s):

```bash
curl -X DELETE http://127.0.0.1:6333/collections/<name>
rm -f ~/ai/local-ai-stack/rag-collections/<name>.json
```

## Lifecycle (launchd)

Autostarts and survives reboot/crash as a LaunchAgent:

```bash
scripts/install-launchd-machine1.sh rag-proxy     # install just the proxy agent
launchctl print gui/$(id -u)/com.localai.rag-proxy | grep -E 'state|pid'
curl -s http://127.0.0.1:9200/healthz             # {"service":"rag-proxy","ok":true,...}
launchctl bootout gui/$(id -u)/com.localai.rag-proxy   # stop
```

Logs: `~/ai/logs/rag-proxy.log` (app) and `~/ai/logs/rag-proxy-launchd.{out,err}`.

## Behavior & guarantees

- **Fail-open, scoped.** Only the *retrieval* step is fail-open: Qdrant down, embedder error, or
  retrieval over `RAG_TIMEOUT_MS` (5000) → forward the request **unchanged**. Genuine proxy/forward
  errors surface as `502` (never faked success). Verified live: with Qdrant killed, the proxy still
  served.
- **Streaming.** SSE is forwarded incrementally (httpx `stream=True`), so the first token is not
  delayed. Client disconnects close the upstream stream.
- **Body fidelity.** Only the last user message's content is rewritten; every other field
  (`model`, `temperature`, `stream`, `logprobs`, …) is preserved.
- **Chat-only.** Only `POST /v1/chat/completions` is ever augmented. `/v1/models`, `/v1/embeddings`,
  and everything else are transparent pass-through.
- **Local-only.** Binds `127.0.0.1` by default (optionally a Thunderbolt-bridge IP via
  `RAG_PROXY_BRIDGE_HOST`). The "api-key" is a **routing label, not a credential** — only expose the
  bridge on a trusted link.

## Observability

The grounded prompt is recorded by the meter and visible in the dashboard's request content (you can
see the injected `--- context ---` block). Requests are **attributed by collection name** in the
dashboard's "Top Clients": because the proxy forwards the original `Authorization: Bearer <collection>`
to the meter, and the meter labels any safe identifier by its key, per-project RAG traffic shows up as
`peptides`, `my-mordor`, etc. (Credential-looking tokens like `sk-…`, and requests with no api-key,
still collapse to `unknown` so secrets never surface in the dashboard.)

## Does it actually help? (measured, not assumed)

A/B'd via the eval harness on the **peptides** project (8 project-specific questions, judged blind by
the reviewer model, judge κ=1.0):

| arm | McNemar | mean generation | completion tokens | + retrieval |
|---|---|---|---|---|
| baseline | — | 16.0 s | 182 | — |
| **rag** | **6W / 0L / 2T, p=0.031** ✅ | 8.9 s | 80 | +1.78 s |

RAG **significantly beat baseline** on project-specific knowledge — and was *faster* end-to-end
(~10.7 s vs 16.0 s): grounding let the model answer concisely (80 vs 182 tokens) instead of padding
toward the token cap with guesses. The ~1.8 s retrieval cost was more than repaid by shorter
generation.

**Where it's not worth it:** for generic, off-domain questions the score gate returns nothing, so the
proxy auto-skips and the answer is identical to baseline. Measured: a contrast eval of 6 generic CS
questions against the same peptides collection scored **0W / 0L / 6T, p=1.000** — RAG was a true
no-op (per-case latencies within ~0.1 s of baseline; retrieval returned 0 hits every time). Config:
`local-ai-dashboard/eval/eval-config-peptides-general.json`. **Takeaway:** RAG clearly helps for
project-specific factual recall and is a deliberate, measured no-op for general questions — so it is
safe to route all traffic through the proxy. Re-run the A/B per project before assuming it helps there.

## v1 scope — honest about what's deferred

Built (v1): transparent proxy, per-project collection routing, no-downtime ingest + calibration,
fail-open, streaming, launchd, per-collection gate config shared with the eval arm.

Deferred (documented, not built): a standalone persistent `/embeddings` service (the proxy keeps the
embedder resident, which covers the interactive case); a re-rank model; auto-reindex / file-watching
(ingest is a one-command manual step); model-aware auto-routing (use `x-rag-upstream` or one proxy
per upstream); meter schema changes to tag RAG vs plain (an `x-rag-applied` request header is already
forwarded for a future, zero-cost upgrade).

See also: [`rag.md`](rag.md) (the toolkit + conservative-retrieval rationale),
[`OPERATIONS.md`](OPERATIONS.md), and the spec/plan in `plans/2026-06-17-rag-proxy-{spec,plan}.md`.
