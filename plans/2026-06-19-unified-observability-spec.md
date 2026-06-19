# Spec: Unified Model Observability — every model in one dashboard

Date: 2026-06-19
Status: DRAFT (multi-model review incorporated; awaiting user approval)
Repos touched: `server-setup` (this repo), `local-ai-dashboard` (the meter + dashboard)

## Revisions from multi-model review (incorporated)

Reviewed via `mmr review` (Claude + Codex + Gemini, reconciled). Five P1 findings, all fixed below:

1. **Secret never in logs/DB** — outbound provider key is set on a *separate* header set; the real
   `Authorization` is redacted from capture, error detail, debug logs, and every telemetry row, with
   tests asserting it. (Component A, acceptance, test plan, risks.)
2. **Loopback-only telemetry** — the OTLP receiver binds `127.0.0.1` only (no `0.0.0.0` Docker
   publish); acceptance check that it is unreachable off-machine. (Component E, acceptance.)
3. **GLM OpenAI-compatible id is `glm-5.2`** (not `glm-5.2[1m]`, which is a Claude-Code switching
   alias); 1M context is expressed via OpenCode `limit.context`. (Components C, D; facts table.)
4. **Reported path needs a real receiver** — a stock collector can't emit a bespoke JSON to `:9100`;
   replaced with a small `otel-usage-bridge` (OTLP/HTTP receiver → normalize → reported rows).
   (Component E, files, tasks.)
5. **No prompt content from Gemini/Codex** — `GEMINI_TELEMETRY_LOG_PROMPTS=false`, traces off,
   Codex `log_user_prompt=false`, and the bridge defensively strips any `prompt`/`gen_ai.*.messages`
   fields before storage. (Component E, acceptance, risks.)

## Goal

Make the local AI dashboard the single place to see **every model the user runs**, and add
**GLM-5.2** + **DeepSeek** to the workflow via the **OpenCode** CLI and the **MMR** (Multi-Model
Review) CLI.

Concretely, three model classes flow into one dashboard:

1. **Local models** (orchestrator / developer / reviewer) — already metered. *(unchanged)*
2. **Paid API models** (GLM-5.2 via Z.ai, DeepSeek) — **metered**: routed through the meter so the
   dashboard records the full request (prompt/response/tokens/latency) and, where billing is
   per-token, the **dollar cost**.
3. **Subscription CLIs** (Claude Code, Codex, Gemini) — **reported**: their own
   OpenTelemetry (OTLP) usage export is ingested so token/cost/model usage shows in the dashboard,
   without proxying their authenticated traffic.

Plus the tooling that uses these models:

4. **OpenCode** becomes the multi-provider daily agent (local + GLM + DeepSeek, all via the meter).
5. **MMR** gains GLM-5.2 and DeepSeek as review channels (through OpenCode), for a diverse
   local-+-two-frontier-family review panel.

## Non-goals

- **Running GLM-5.2 locally.** 753B-param MoE; it cannot fit the user's Macs. Subscription only.
- **Proxying the subscription CLIs' traffic** (Claude Code / Codex / Gemini). They are
  OAuth-authenticated first-party tools speaking non-OpenAI protocols; routing them through the
  meter would force per-token API billing instead of the flat subscription, require MITM of an
  authenticated HTTPS session, and need three new wire-format parsers. We ingest their telemetry
  instead. See "Why telemetry, not proxy" below.
- **Capturing prompt/response content for the reported (subscription-CLI) sources.** OTLP usage
  export is metrics/events (tokens, cost, model). Prompt logging is opt-in and privacy-sensitive;
  out of scope for v1. Reported rows store usage, not content.
- **Changing the two-machine architecture.** M1 control plane + M2 worker stay exactly as they are.
- **RAG-grounding the remote models by default.** Composable later via the existing rag-proxy
  (`x-rag-upstream`); off by default to keep this focused.

## Current system summary

- **Meter** (`local-ai-dashboard/src/meter`, Node/TS): a logging proxy on `127.0.0.1:9001/9002/9003`
  that forwards OpenAI-compatible traffic to the local upstreams and records telemetry to SQLite
  (`~/ai/dashboard/telemetry.db`). Port → upstream map in `upstreams.ts`; per-request forwarding +
  capture in `proxy.ts`. Attribution label is computed from the request's `Authorization: Bearer
  <key>` **before** forwarding (`proxy.ts` line ~48). Telemetry parsing assumes the **OpenAI Chat
  Completions** shape.
- **Ingest** path on `:9100` already exists (the M2 collector POSTs usage to M1). Reused below.
- **rag-proxy** on `:9200` sits in front of the meter for per-project RAG. Supports `x-rag-upstream`.
- **Dashboard** (Next.js, `:3111`) renders telemetry. Tracks tokens + latency; **no dollar cost**
  (local models are free).
- **OpenCode** `1.16.0` installed; global config `~/.config/opencode/opencode.json` (currently none).
  Headless: `opencode run "<msg>" --model <provider>/<model> [--variant high|max] [--format json]`.
- **MMR** `1.6.1`: review channels are **CLI commands** (`claude -p`, `gemini`, `codex exec`,
  `grok`, `agy`), each with a `parser`. Project config is `.mmr.yaml`; channels also live in a
  global config. Channels run a command and parse stdout into findings.

## Verified external facts (researched 2026-06-19)

| Provider | OpenAI base URL | Model id(s) | Billing |
|---|---|---|---|
| Z.ai GLM Coding Plan | `https://api.z.ai/api/coding/paas/v4` | OpenAI-compatible id: **`glm-5.2`** (`glm-5.2[1m]` is a *Claude Code* model-switch alias, not a raw API id; request 1M context via the client's context limit) | flat subscription quota (tiers ~$3–$80/mo); coding endpoint draws on plan, no per-token charge |
| DeepSeek | `https://api.deepseek.com` (root; **no `/v1`**) | `deepseek-v4-pro`, `deepseek-v4-flash` | pay-as-you-go per token |

DeepSeek pricing (USD / 1M tokens): **v4-flash** $0.14 in (miss) / $0.0028 cache-hit / $0.28 out;
**v4-pro** $0.435 in (miss) / $0.003625 cache-hit / $0.87 out.
GLM pay-as-you-go list (only if the non-subscription endpoint is ever used): ~$1.40 in / $0.26
cached / $4.40 out.

Subscription-CLI OTEL export (all export OTLP to a configurable local endpoint, default `:4317`):

| CLI | Enable | Endpoint var | Emits |
|---|---|---|---|
| Claude Code | `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_METRICS_EXPORTER=otlp`, `OTEL_LOGS_EXPORTER=otlp` | `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL` | token counts by type, **cost (USD)**, model, per `api_request` event |
| Gemini CLI | `GEMINI_TELEMETRY_ENABLED=true`, `GEMINI_TELEMETRY_TARGET=local`, **`GEMINI_TELEMETRY_LOG_PROMPTS=false`** (defaults ON — must disable), traces off | `GEMINI_TELEMETRY_OTLP_ENDPOINT`, `GEMINI_TELEMETRY_OTLP_PROTOCOL` | `gen_ai.client.token.usage`, `gemini_cli.token.usage` (input/output/thought/cache/tool by model). ⚠️ logs can include `prompt`/`gen_ai.input.messages`/`gen_ai.output.messages` unless disabled |
| Codex | `~/.codex/config.toml` `[otel]` (exporter `otlp-http`/`otlp-grpc`), keep **`log_user_prompt=false`** (default) | endpoint/protocol/headers in config | token usage + events |

## Proposed architecture

```
                                       ┌─ :9001 → orchestrator (M1 local)   metered
 OpenCode ─┐                           ├─ :9002 → developer    (M2 local)   metered
 MMR ──────┤                           ├─ :9003 → reviewer     (M2 local)   metered
 (any OpenAI│  meter (127.0.0.1) ──────┤
  client)   │   key-swap + path-norm   ├─ :9004 → GLM-5.2  → api.z.ai       metered (NEW)
           ─┘                           └─ :9005 → DeepSeek → api.deepseek   metered (NEW)
                                                   │
 Claude Code ─┐   OTLP (loopback only)             ▼
 Codex ───────┼─→ otel-usage-bridge ─→ :9100 ingest ─→ telemetry.db ─→ dashboard :3111
 Gemini ──────┘   127.0.0.1:4318       (normalized usage rows, source=reported, content stripped)
                  (OTLP/HTTP receiver →
                   normalize → strip content)
```

Two ingestion paths land in the **same** `telemetry.db`, distinguished by a new `source` column:

- `source='metered'` — full request rows from the meter (existing behavior + the two new ports).
- `source='reported'` — usage rows synthesized from subscription-CLI OTLP events (no content).

### Component A — meter fronts remote providers (metered path)

`local-ai-dashboard/src/meter`:

- **`upstreams.ts`**: extend `UpstreamDef` with `kind: 'local' | 'remote'`, optional `apiKeyEnv`
  (env var holding the real key), and optional `stripV1: true`. Add:
  - `9004` → `{ name:'glm', target:'https://api.z.ai/api/coding/paas/v4', machine:'remote', kind:'remote', apiKeyEnv:'ZAI_API_KEY', stripV1:true }`
  - `9005` → `{ name:'deepseek', target:'https://api.deepseek.com', machine:'remote', kind:'remote', apiKeyEnv:'DEEPSEEK_API_KEY', stripV1:true }`
  - Add `'glm' | 'deepseek'` to the `Upstream` union and `'remote'` to `Machine` in `shared/types.ts`.
- **`proxy.ts`**: after the attribution label is computed (it already is, before forwarding):
  1. **Key injection on a separate outbound header set.** Read each remote key from
     `process.env[apiKeyEnv]` **at startup** into a frozen lookup (fail fast with a clear error if a
     configured remote port has no key — never forward the routing label to a provider). Build the
     outbound headers as a fresh object; set `outboundHeaders['authorization'] = 'Bearer ' + key`
     there. **The inbound header set used for attribution/capture is never mutated and never carries
     the real key**, so nothing downstream can serialize it.
  2. **Redaction is mandatory, not incidental.** The real `Authorization` value must never appear in:
     telemetry DB rows, captured content, `error_detail`, or any debug/console log. Any code path
     that could serialize headers redacts `authorization`/`proxy-authorization` to `***`. (Today the
     capture stores only prompt/response bodies, but we add this guard + tests so a future log line
     can't leak the key.)
  3. **Path normalization**: the forward target is `upstream.target + outPath`, where `outPath` is the
     incoming path with a single leading `/v1` removed iff `upstream.stripV1` (remote only). So
     `:9005/v1/chat/completions` → `https://api.deepseek.com/chat/completions`, and
     `:9004/v1/chat/completions` → `https://api.z.ai/api/coding/paas/v4/chat/completions`. Local
     upstreams keep the path verbatim.
- Forwarding/streaming/capture are otherwise unchanged (the remote responses are OpenAI Chat
  Completions shape, which the existing capture already parses).

### Component B — dollar cost + source type (dashboard)

- **Price table** `src/shared/prices.ts`: `model id → { input, cachedInput, output, billing:
  'metered' | 'subscription' }` per 1M tokens, for `deepseek-v4-pro`, `deepseek-v4-flash`,
  `glm-5.2` (`billing:'subscription'`), etc. Single source of truth; unit-tested.
- **Schema**: add `source TEXT NOT NULL DEFAULT 'metered'` and `cost_usd REAL` to the request rows
  table (additive migration; existing rows default to `metered`, `cost_usd` null).
- **Cost computation** (`record.ts` or a small `cost.ts`): on insert, for `billing:'metered'`
  models compute `cost_usd` from usage tokens × price (use cached-input price for the
  prompt-cache-hit portion when the provider reports it). For `billing:'subscription'` models, leave
  `cost_usd` null and surface **token volume against the plan** instead of a fake per-request price.
  Reported rows carry the vendor's own `cost_usd` when present (Claude Code), else computed from
  tokens, else null.
- **Dashboard UI**: a cost column / per-model + per-day + per-month totals; metered models show
  dollars, subscription models show usage-vs-quota, reported models are clearly tagged
  "reported (usage only — no content captured)".

### Component C — OpenCode as the multi-provider agent

Global `~/.config/opencode/opencode.json` defines one `@ai-sdk/openai-compatible` provider per
meter port. Each `baseURL` is the local meter; each `apiKey` is a **routing label**, not a secret
(so OpenCode holds nothing sensitive). Local model ids are taken from each port's `/v1/models`.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "local-dev":    { "npm":"@ai-sdk/openai-compatible", "name":"Local Developer (metered)",
                      "options": { "baseURL":"http://127.0.0.1:9002/v1", "apiKey":"opencode" },
                      "models": { "<id-from-/v1/models>": { "name":"Developer 27B" } } },
    "local-review": { "...":"…9003…" },
    "local-orch":   { "...":"…9001…" },
    "glm":          { "npm":"@ai-sdk/openai-compatible", "name":"GLM-5.2 (Z.ai, metered)",
                      "options": { "baseURL":"http://127.0.0.1:9004/v1", "apiKey":"opencode" },
                      "models": { "glm-5.2": { "name":"GLM-5.2",
                                  "limit": { "context":1000000, "output":65536 } } } },
    "deepseek":     { "npm":"@ai-sdk/openai-compatible", "name":"DeepSeek (metered)",
                      "options": { "baseURL":"http://127.0.0.1:9005/v1", "apiKey":"opencode" },
                      "models": { "deepseek-v4-pro": { "name":"DeepSeek v4 Pro" },
                                  "deepseek-v4-flash": { "name":"DeepSeek v4 Flash" } } }
  }
}
```

### Component D — MMR review channels (through OpenCode)

Add two channels (global MMR config or repo `.mmr.yaml`) that shell out to OpenCode headless:

```yaml
channels:
  opencode-glm:
    command: opencode run
    flags: ["--model", "glm/glm-5.2", "--format", "default"]
    parser: default
  opencode-deepseek:
    command: opencode run
    flags: ["--model", "deepseek/deepseek-v4-pro", "--format", "default"]
    parser: default
```

Exact prompt-passing (positional message vs stdin) and parser choice are validated with one real
`mmr review` during implementation; the `claude -p` channel is the working reference.

### Component E — subscription-CLI telemetry ingestion (reported path)

A stock OpenTelemetry Collector can receive/transform OTLP but its exporters emit OTLP or
backend-specific formats — **not** a bespoke JSON body to our `:9100` ingest. So the reported path
needs a tiny purpose-built receiver, not a generic collector pipeline.

- **`otel-usage-bridge`** (new small service in `local-ai-dashboard`, Node/TS): a minimal **OTLP/HTTP
  receiver** that:
  - **Binds `127.0.0.1` only** (no `0.0.0.0`). If containerized, the compose publish is
    `127.0.0.1:4318:4318` — never a bare `4318:4318` (which binds all interfaces and would expose CLI
    telemetry to the LAN). Default: run it in-process with the meter on `127.0.0.1:4318`.
  - Parses OTLP metrics + logs (via `@opentelemetry/otlp-transformer`) for `OTEL_*`-exported data
    from the three CLIs, maps each vendor's metric/event names to a normalized usage event
    (Claude Code `api_request` → tokens + `cost_usd`; Gemini `gemini_cli.token.usage` → token
    breakdown; Codex token events), and writes a `source='reported'` row.
  - **Content stripping is enforced at the boundary**: the bridge drops any `prompt`,
    `gen_ai.input.messages`, `gen_ai.output.messages`, or body-like fields **before** anything is
    written or logged — a defense-in-depth backstop even if a CLI is misconfigured to emit prompts.
    Reported rows always store `content=null`.
- **Ingest mapping** (`src/meter/ingest.ts`): accept the normalized usage event
  `{ source:'reported', client:'claude-code'|'codex'|'gemini', model, prompt_tokens,
  completion_tokens, cost_usd?, ts }` and write the row with `source='reported'`, `content=null`.
  (The bridge may call this directly in-process, or POST to `:9100` if run as a separate container.)
- **Enablement**: a documented one-time per-CLI setup pointing each tool's OTLP exporter at
  `127.0.0.1:4318`, **with prompt logging explicitly off**: Claude Code
  (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_*` → loopback), Gemini (`.gemini/settings.json`:
  `GEMINI_TELEMETRY_ENABLED=true`, `target=local`, `GEMINI_TELEMETRY_LOG_PROMPTS=false`, traces off),
  Codex (`~/.codex/config.toml` `[otel]` exporter `otlp-http` → loopback, `log_user_prompt=false`).
  Provided as a copy-paste block + a `scripts/enable-cli-telemetry.sh` helper.

### Component F — secrets

```bash
launchpad secrets set ZAI_API_KEY
launchpad secrets set DEEPSEEK_API_KEY
```

The meter's launch wrapper runs under `launchpad secrets run -- …` (or `op run`) so `ZAI_API_KEY` /
`DEEPSEEK_API_KEY` are injected into the meter process memory at startup — never written to the
launchd plist or the repo. OpenCode and MMR hold no provider keys (they send routing labels).

## Why telemetry, not proxy (for the subscription CLIs)

1. **Billing/auth**: a custom base URL is the API-key path → per-token billing instead of the flat
   subscription. Staying on the subscription would require MITM of the vendor's OAuth HTTPS session
   (fragile, unsupported, ToS-gray).
2. **Protocol**: Anthropic Messages / OpenAI Responses / Google generateContent are each non-OpenAI;
   the meter would forward but capture nothing useful without three new parsers to maintain.
3. **Motivation**: flat-rate subscriptions have no runaway per-token bill to catch; usage visibility
   (which OTEL gives directly) is the actual goal.

## Files expected to change

`local-ai-dashboard`:
- `src/meter/upstreams.ts` (+ test) — remote upstream defs, `apiKeyEnv`, `stripV1`.
- `src/shared/types.ts` — `Upstream`/`Machine` unions, `RequestRow.source`, `RequestRow.cost_usd`.
- `src/meter/proxy.ts` (+ test) — key injection, path normalization.
- `src/shared/prices.ts` (+ test) — price table.
- `src/meter/record.ts` / new `src/meter/cost.ts` (+ test) — cost computation, source tagging.
- `src/meter/ingest.ts` (+ test) — accept reported usage events.
- `src/meter/redact.ts` (+ test) — header redaction helper (`authorization`/`proxy-authorization`).
- `src/otel-bridge/` (+ test) — `otel-usage-bridge` OTLP/HTTP receiver, loopback-bound, content-stripping.
- dashboard UI components — cost/source columns + totals.
- DB migration for `source` + `cost_usd`.
- meter launch wrapper / launchd — secret injection.

`server-setup`:
- `configs/opencode/opencode.json.example` — provider config template.
- `configs/mmr/channels.example.yaml` — the two OpenCode channels.
- `scripts/enable-cli-telemetry.sh` — one-time OTLP enablement for the three CLIs.
- `docs/` — new `dev-stack-models.md` (OpenCode + MMR + providers) and
  `observability.md` (the two-path model); cross-links from `README.md`, `OPERATIONS.md`.
- `configs/env.machine1.example` — note the two new secret names.

## Step-by-step implementation tasks

Phase 1 — metered remote providers (smallest shippable slice):
1. `shared/types.ts`: add unions + `source`/`cost_usd` (additive).
2. `upstreams.ts` + test: add `9004`/`9005`, `apiKeyEnv`, `stripV1`.
3. `redact.ts` + test: redact `authorization`/`proxy-authorization` in any serialized headers.
4. `proxy.ts` + test: startup key read (fail-fast), **separate outbound header set** with the real
   key (inbound/capture headers never mutated), `/v1` strip for remote, and a test asserting the
   real key never appears in the recorded row, `error_detail`, or logs.
5. Secret injection in the meter launch wrapper; `launchpad secrets set` the two keys.
6. Live smoke: `curl :9005/v1/chat/completions` (DeepSeek `deepseek-v4-flash`, cheapest) and `:9004`
   (GLM `glm-5.2`) return 200; dashboard shows a `metered` row with the right `client`/`model`.

Phase 2 — cost + source in the dashboard:
6. `prices.ts` + test.
7. `cost.ts` + `record.ts` wiring + test; DB migration.
8. Dashboard cost/source UI; verify DeepSeek shows $ and GLM shows usage-vs-quota.

Phase 3 — OpenCode + MMR:
9. Write `opencode.json` (resolve local ids via `/v1/models`); `opencode run` against each provider.
10. Add the two MMR channels; run one real `mmr review`; confirm metered rows appear.

Phase 4 — reported path (subscription CLIs):
11. `otel-usage-bridge` (loopback `127.0.0.1:4318`, OTLP parse, content-strip) + `ingest.ts`
    reported-event mapping + tests (incl. a test that an OTLP payload carrying a `prompt` field is
    stored with `content=null`).
12. `enable-cli-telemetry.sh` (prompt logging off for all three); enable Claude Code first (it emits
    `cost_usd`), then Gemini (`GEMINI_TELEMETRY_LOG_PROMPTS=false`), then Codex (`log_user_prompt=false`).
13. Verify each CLI's usage appears as `source='reported'` rows, tagged usage-only, content null; and
    that `:4318` is not reachable from another host on the LAN.

Phase 5 — docs:
14. `dev-stack-models.md`, `observability.md`, cross-links, env notes.

## Acceptance criteria

- A request to `:9004`/`:9005` is forwarded with the **real** provider key (never the routing label)
  and the correct path; the response streams back unchanged.
- The real provider key **never** appears in the telemetry DB, captured content, `error_detail`, or
  any log line — asserted by an automated test (inbound header set is never mutated; redaction holds).
- The `otel-usage-bridge` (`:4318`) and `:9100` ingest are **not reachable off-machine** (loopback
  bind verified); reported rows always store `content=null` even if a CLI emits prompt fields.
- The dashboard shows, in one place: local (metered, free), DeepSeek (metered, **$**), GLM (metered,
  **usage-vs-quota**), and Claude Code/Codex/Gemini (reported, usage-only, clearly tagged).
- `opencode run --model glm/glm-5.2 "hi"` and `--model deepseek/deepseek-v4-pro "hi"` and a local
  provider all return answers, and each shows up as a metered row attributed to a sensible client.
- `mmr review` can include `opencode-glm` and `opencode-deepseek` channels and produces findings.
- Enabling Claude Code telemetry produces `reported` rows with token + cost data.
- No provider secret appears in any committed file, the launchd plist, OpenCode config, or MMR config.
- Existing local-model metering, RAG proxy, and the `unknown`-attribution fix are unchanged
  (regression check: existing meter tests still pass).

## Test plan

- **Unit**: `upstreams` (new defs), `proxy` (key swap with a fake remote upstream asserts the
  **outbound** `Authorization` = real key, the **recorded row / error_detail / logs never contain
  the key**, and `/v1` stripped; local upstream unchanged), `redact` (headers masked), `prices`,
  `cost` (metered math + subscription→null + cached-input portion), `ingest`/`otel-usage-bridge`
  (reported event → row; an OTLP payload with a `prompt`/`gen_ai.*.messages` field stores
  `content=null`).
- **Integration**: in-process fake remote upstream (as the existing rag-proxy tests do) for path +
  key assertions without hitting the network.
- **Live smoke**: real `curl` to DeepSeek (cheapest model) and GLM; one `opencode run` per provider;
  one `mmr review`; enable Claude Code OTEL and confirm a reported row.
- **Regression**: full existing meter test suite green; dashboard renders with mixed sources.

## Rollback plan

Incremental and isolated:
- Remove ports `9004`/`9005` from `upstreams.ts` → remote providers simply disappear; local path
  untouched.
- `source`/`cost_usd` are additive nullable columns; revert UI to ignore them with no data loss.
- Delete OpenCode providers / MMR channels (pure config).
- Stop the `otel-usage-bridge` → reported path goes quiet; metered path unaffected.
- `launchpad secrets` removal revokes remote access cleanly.

## Docs updates

- New `docs/dev-stack-models.md` (OpenCode providers, MMR channels, model ids, headless usage).
- New `docs/observability.md` (the metered-vs-reported model; what's captured for each; the OTEL
  enablement steps).
- `README.md` + `docs/OPERATIONS.md` cross-links; `configs/env.machine1.example` secret-name notes.

## Risks and edge cases

- **GLM ToS gray-area (accepted, option A)**: routing the *subscription* coding endpoint through a
  local logging proxy is gray under Z.ai's "supported tools only" terms. Low risk for a personal,
  transparent proxy; documented. Mitigation if ever flagged: switch the `9004` target to the
  pay-as-you-go endpoint (`/api/paas/v4`) or point OpenCode at Z.ai directly.
- **DeepSeek model churn**: `deepseek-chat`/`deepseek-reasoner` are deprecated (gone 2026-07-24); we
  use `deepseek-v4-pro`/`-flash`. Price table is the single place to update.
- **Secret in logs/DB (P1, fixed)**: the real key is set only on a separate outbound header set, the
  inbound/capture set is never mutated, and `authorization` is redacted in any serialized headers —
  with a test asserting the key is absent from rows/`error_detail`/logs.
- **Loopback exposure (P1, fixed)**: the OTLP receiver and ingest bind `127.0.0.1` only; any
  containerized form publishes `127.0.0.1:4318:4318`, never `4318:4318`. Acceptance verifies it's
  unreachable off-machine.
- **Gemini/Codex prompt leakage (P1, fixed)**: Gemini telemetry defaults prompt-logging ON, so
  enablement sets `GEMINI_TELEMETRY_LOG_PROMPTS=false` (and Codex `log_user_prompt=false`); the
  bridge additionally strips any prompt/message fields before storage as defense-in-depth.
- **GLM model id (P1, fixed)**: use `glm-5.2` on the OpenAI-compatible path; `glm-5.2[1m]` is a
  Claude-Code switch alias. The live smoke test confirms the exact accepted id before we rely on it.
- **Reported-source fidelity**: usage/cost only, no prompt/response content; the UI must say so to
  avoid implying full capture. (Mirrors the prior honesty about the `unknown` attribution.)
- **OTEL cost units**: Claude Code reports `cost_usd` directly; Gemini/Codex report tokens — compute
  from the price table or show tokens-only when a model isn't priced.
- **Bridge as a moving part**: if `otel-usage-bridge` is down, reported rows pause (metered path
  unaffected). It's small and in-process by default to minimize this.
- **Secret-at-startup**: a configured remote port with a missing key must fail fast at meter launch
  with a clear message, not silently forward the routing label to the provider.
- **Path-normalization scope**: `stripV1` must remove only a single leading `/v1` and only for
  remote upstreams, so `/v1/models` and other paths still resolve correctly per provider.
```

