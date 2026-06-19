# Unified observability — every model in one dashboard

The dashboard now shows **every model you run**, via two ingestion paths into the same telemetry DB.
Rows carry a `source` so the two are never confused.

```
                                   ┌─ :9001 orchestrator (M1)  ┐
 OpenCode / MMR / any        meter ├─ :9002 developer    (M2)  │ metered  (full request + cost)
 OpenAI-compatible client ─────────┼─ :9003 reviewer     (M2)  │  source='metered'
                                   ├─ :9004 GLM-5.2  → api.z.ai │
                                   └─ :9005 DeepSeek → deepseek ┘
 Claude Code / Codex / Gemini ── OTLP ─→ otel-usage-bridge :4318 ─→  reported (usage only, no content)
   (loopback)                                                         source='reported'
```

## Metered path (full fidelity)

Local models, **GLM-5.2**, and **DeepSeek** route through the meter. It records the full request
(prompt/response/tokens/latency) and a **dollar cost**:

- **DeepSeek** is pay-as-you-go → real `cost_usd` per request (price table in
  `local-ai-dashboard/src/shared/prices.ts`).
- **GLM-5.2** is a flat **subscription** (Coding Plan) → `cost_usd` is null on purpose (per-token
  dollars would mislead); the dashboard shows token **volume** instead.
- **Local** models are free → `cost_usd` null.

See the cost page's **"Actual spend — paid APIs"** section. The meter holds the real provider keys;
clients only ever send a routing **label** (the api-key), which becomes the dashboard "client" name.

**Enabling the paid providers:** set the keys, then restart the meter.

```bash
launchpad secrets set ZAI_API_KEY        # GLM Coding Plan key
launchpad secrets set DEEPSEEK_API_KEY   # DeepSeek key
# either: put them in ~/ai/dashboard/dashboard.env (git-ignored), OR set
#   METER_SECRETS_VIA_LAUNCHPAD=1 in dashboard.env to inject from 1Password at launch.
launchctl kickstart -k gui/$(id -u)/com.localai.dashboard.meter
```

The meter **skips** a remote port whose key is unset (logged) — it never crashes the local stack, and
never forwards a routing label to a provider as if it were a key. So `:9004`/`:9005` simply aren't
served until the keys exist.

## Reported path (subscription CLIs — usage only)

Claude Code, Codex, and Gemini are OAuth/first-party tools we don't proxy (doing so would force
per-token API billing and break their auth). Instead we ingest their **OpenTelemetry** usage export:

```bash
# 1) start the meter with the bridge on (loopback :4318)
echo 'OTEL_BRIDGE=1' >> ~/ai/dashboard/dashboard.env
launchctl kickstart -k gui/$(id -u)/com.localai.dashboard.meter
# 2) point the three CLIs at it (prompt logging forced OFF, content stripped at the bridge)
scripts/enable-cli-telemetry.sh
```

Reported rows store **usage only** — `cost_usd` where the CLI reports it (Claude Code), token volume
otherwise, and **never** prompt/response content. The bridge binds `127.0.0.1` only and recursively
strips any prompt/message field as a backstop; it stores OTLP **metrics**, never log bodies.

**Known limit (v1):** the bridge decodes OTLP/HTTP **JSON**. A CLI that only emits protobuf
(`http/protobuf`) won't be parsed yet — run an OpenTelemetry Collector to translate protobuf→JSON to
the bridge, or use `OTEL_EXPORTER_OTLP_PROTOCOL=http/json` where the CLI supports it. Tracked as a
follow-up; the normalization + privacy logic is already built and tested.

## Why telemetry, not proxy, for the subscription CLIs

1. A custom base URL is the API-key path → per-token billing instead of the flat subscription.
2. Each speaks a different non-OpenAI protocol (Anthropic Messages / OpenAI Responses / generateContent).
3. Flat-rate plans have no runaway per-token bill to catch — usage visibility (what OTEL gives) is the goal.

See `plans/2026-06-19-unified-observability-spec.md` and `dev-stack-models.md`.
