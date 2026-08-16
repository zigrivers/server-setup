# Local model brief (paste this into an agent's context)

Everything an AI agent needs to call this stack correctly. Copy the fenced block below verbatim;
the notes after it explain the reasoning for a human.

```text
LOCAL MODEL STACK — how to call it

Two Mac Studios (M3 Ultra, 512 GB each) serving open-weight models over an OpenAI-compatible API.
Machine 1 is the control plane; Machine 2 is the inference worker on 10.10.10.2.

ENDPOINTS — always use the 9xxx "meter" ports, never the raw 800x ports.
  http://127.0.0.1:9001/v1   orchestrator  Qwen3.6-35B-A3B (MoE, 8-bit)   fast, general
  http://127.0.0.1:9002/v1   developer     Qwen3.8-27B (8-bit)            code writing
  http://127.0.0.1:9003/v1   reviewer      Qwen3.8-27B (8-bit)            code review, max 2 in flight
  http://127.0.0.1:9006/v1   review router prefers reviewer, spills to orchestrator when busy
  http://127.0.0.1:9004/v1   GLM           PAID cloud (z.ai) — costs money
  http://127.0.0.1:9005/v1   DeepSeek      PAID cloud — costs money
  http://127.0.0.1:9200/v1   RAG proxy     = developer, with retrieval injected (see RAG below)
All three local models: 262,144-token context. Roughly 12-20 tokens/sec generation.

RULE 1 — DISCOVER THE MODEL ID, NEVER GUESS IT.
  GET {endpoint}/v1/models and use the id that starts with "/" (a filesystem path).
  The server LOADS whatever id you send. An unknown id is fetched from HuggingFace (fails, or
  worse, downloads); a stale-but-real id loads a SECOND copy of old weights into memory.
  Omitting "model" entirely is also safe — the endpoint uses its default.

RULE 2 — SEND A ROUTING LABEL AS THE API KEY, NOT A SECRET.
  Authorization: Bearer <your-agent-name>      e.g. Bearer claude-code
  There is no auth on local endpoints. The label is used for per-client attribution in telemetry.
  Never send a real provider key (anything starting with sk-); the meter injects real keys itself
  for the paid cloud ports.

RULE 3 — THESE ARE THINKING MODELS, AND QWEN3.8 THINKS A LOT.
  Responses carry both "reasoning" and "content". With a small max_tokens the model spends the whole
  budget reasoning and returns EMPTY content — it does not truncate the answer, there is no answer.
  Reasoning scales with how open-ended the prompt is:
    closed question ("name two causes of X")      -> answers inside 256 tokens, seconds
    open-ended review ("list every bug")          -> p50 47s, p90 314s, worst seen 401s / 8,000 tokens
  So: use max_tokens >= 12000 for open-ended analysis and review, >= 800 for ordinary answers.
  DO NOT set enable_thinking:false to make it fast — measured over 18 planted bugs that costs 17
  points of recall (89% -> 72%) and produced the only false alarm in the run. Speed there is bought
  with missed bugs.

RULE 4 — PREFER LOCAL. Ports 9004 and 9005 bill a vendor per token. 9001/9002/9003/9006 are free.

RAG (optional, project-grounded answers):
  Call http://127.0.0.1:9200/v1 exactly like the developer endpoint and add:
    x-rag-collection: <name>     (or send the collection name as the Bearer label)
  Collections: cortex, my-mordor, nibble, peptides, rumble, scaffold, server_setup, sona, surface
  — one per project under ~/Developer. Retrieval is conservative: if nothing clears the relevance
  gate, your prompt is forwarded unchanged. Unknown collection = plain passthrough, no error.

EXAMPLE
  MODEL=$(curl -s http://127.0.0.1:9003/v1/models | python3 -c \
    'import json,sys; print(next(m["id"] for m in json.load(sys.stdin)["data"] if m["id"].startswith("/")))')
  curl -s http://127.0.0.1:9003/v1/chat/completions \
    -H 'Content-Type: application/json' -H 'Authorization: Bearer my-agent' \
    -d "{\"model\":\"$MODEL\",\"max_tokens\":1200,\"messages\":[{\"role\":\"user\",\"content\":\"...\"}]}"

PRIVACY: every request through the meter is recorded locally, prompt and response text included.
Do not send anything through it you would not want stored on this machine.
```

## Why each rule is there

**Rule 1** is the one that actually bites. `mlx_lm.server` treats the `model` field as a load
instruction, not a selector. Two real incidents on this stack: clients still sending the reviewer's
pre-swap HuggingFace id kept getting the old slow weights after an upgrade, and the repo's own
smoke test loaded a second 65 GB copy on Machine 1 while reporting "OK". The meter now pins the
local endpoints (`METER_DEV_MODEL` / `METER_REVIEW_MODEL` in `~/ai/dashboard/dashboard.env`), which
protects traffic through 9xxx — the raw 800x ports have no such guard, which is the other reason to
use the meter ports.

**Rule 2**: `src/meter/upstreams.ts` maps the bearer token to a client label for the dashboard's
attribution views. Anything matching `^sk[-_]` is rejected as a label so a leaked provider key never
lands in telemetry.

**Rule 3**: the dashboard tracks the reasoning share of output tokens ("reasoning tax") precisely
because it is large. Numbers come from the model-comparison harness in `local-ai-dashboard`
(`src/modeleval/`, 18 planted bugs, 4 clean cases, temperature 0), not from a single prompt. The
failure mode when the budget is too small is an empty or mid-thought `content`, not a short answer —
which reads like a broken endpoint if you are not expecting it.

**Reviewer concurrency**: `:9003` is capped at 2 in-flight requests (`METER_REVIEWER_MAX_INFLIGHT`)
so a fan-out cannot thrash one Mac Studio. Excess requests queue rather than fail. `:9006` is the
smarter door for review work — it spills to a healthy idle orchestrator instead of queueing.

**Model roles are convention, not enforcement.** Any endpoint answers any prompt; the split exists
so review work does not evict the developer's prompt cache.

See `docs/MODELS.md` for exact paths, quantizations and the model manifest, and `docs/rag.md` for
how retrieval is gated.
