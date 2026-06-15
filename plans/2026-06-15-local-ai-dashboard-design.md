# Local AI Stack Dashboard — Design Spec

**Date:** 2026-06-15
**Status:** Design approved (pending written-spec review) — precedes the implementation plan.
**Topic:** A web dashboard to monitor all activity on the two-Mac local open-source model stack.

---

## Goal

Give one place to see everything happening on the local models: how fast they are,
whether they're healthy, who's using them, what it's saving versus frontier APIs, and
how the two Macs are holding up — in a browser, easy to read at a glance, viewable from
other devices on the home network.

## Non-goals

- Not a request *gateway* with routing/rate-limiting/caching (the meter only observes; it
  does not load-balance or transform).
- Not a replacement for the existing `local_ai_status` / `preflight` / `audit-stack`
  tooling — it complements them with history and per-request detail.
- Not a multi-tenant or cloud-deployed product. It is personal infrastructure that runs on
  the M1/M2 network only.
- v1 does not store prompt/completion **content** (metrics and metadata only); content
  capture is an opt-in flag added later, off by default.

## Background / the load-bearing constraint

The stack: orchestrator `127.0.0.1:8001` (M1, 35B MoE BF16, fast), developer
`10.10.10.2:8002` and reviewer `10.10.10.2:8003` (M2, dense 27B, slower), all
`mlx_lm.server` OpenAI-compatible endpoints, launchd-managed.

**`mlx_lm.server` exposes no `/metrics` endpoint** (confirmed: `GET :8001/metrics` → 404).
The industry-standard path (vLLM/TGI emit Prometheus metrics → Grafana scrapes) does not
apply. We must *produce* the telemetry ourselves. Chosen approach: a thin observing proxy
in front of the endpoints, plus lightweight hardware/health collectors.

## Users & access

Single user (the owner). The dashboard is **LAN-accessible behind a simple login** so it
can be viewed from a phone or another Mac on the home network. No multi-user roles.

## Decisions captured (from brainstorming)

| Decision | Choice | Why |
|---|---|---|
| Telemetry capture | Thin **fail-open proxy** ("the meter") | Richest data + per-client attribution; never blocks serving |
| Monitoring scope (v1 priorities) | Performance, Reliability, Usage/attribution, Hardware + cost-avoided (all four) | User wants full insight |
| Form factor | **Custom Next.js web app** | Full control of the novel panels; themable; LAN-deployable |
| Access | **LAN-accessible with login**, metrics-only storage by default | View anywhere at home; health data never stored as content |
| Language | **TypeScript** for both meter and dashboard | Best dashboard tool; sufficient + maintainable-by-owner for a low-volume proxy; one language/toolchain |
| Datastore | **SQLite** (WAL mode) | Zero-ops, file-based, ample for this volume |

---

## Architecture overview

Four cooperating parts, all in one new repo (`local-ai-dashboard`):

```
  apps/CLIs ──▶ [ METER :9001/9002/9003 ] ──▶ real model endpoints (8001/8002/8003)
  (Claude,           │  (observe only,            (orchestrator / developer / reviewer)
   Codex,            │   fail-open)
   Antigravity,      ▼
   peptides,     [ SQLite store ] ◀── [ COLLECTOR (M1) ]   [ COLLECTOR (M2) ] ──▶ POST to M1
   MCP tools)        ▲                  (hardware/health samples, both machines)
                     │
              [ DASHBOARD (Next.js, login) ]  ◀── browser on any LAN device
```

**Data flow:** a client calls the meter instead of the model directly → meter forwards to
the real endpoint and streams the response straight back → meter records one row
(out-of-band, never blocking) → collectors periodically write hardware/health samples →
the dashboard reads the SQLite file and renders.

---

## Component 1 — The meter (observing proxy)

**Plain English:** a small program that sits between your apps and the models. Every
request passes through unchanged; it just writes down what happened.

- **Runs on:** M1, launchd-managed (like the rest of the stack). Single Node/TypeScript
  service.
- **Routing — port-per-upstream (drop-in):** listens on `:9001 → :8001`, `:9002 →
  10.10.10.2:8002`, `:9003 → 10.10.10.2:8003`. A client migrates by changing only the
  port in its base URL (`…:8001/v1` → `…:9001/v1`). The real ports stay open, so migration
  is opt-in and reversible per client.
- **Per-client attribution via API key:** each consumer is given a recognizable key
  (e.g. `claude-code`, `codex`, `antigravity`, `peptides`, `mcp-local-review`,
  `mcp-run-plan`). The meter maps key → client label. Unknown key → `unknown` (record key
  prefix + IP + User-Agent as fallback signals). No app currently uses a real key (all send
  `not-needed`), so this is a free signal to add.
- **Streaming-safe:** transparently passes Server-Sent Events through without buffering.
  Captures time-to-first-token (first streamed byte), total latency, and token counts
  (from the final `usage` block for non-stream, or by counting/late-usage for stream).
  Captures `reasoning` vs `content` token split when the response distinguishes them
  (the "reasoning-tax" signal).
- **Fail-open (cardinal rule):** all recording is best-effort and out of the response path
  (e.g. fire-and-forget write / in-memory queue flushed async). If the store is locked,
  the disk is full, or the recorder throws — the request is still forwarded and the
  upstream response returned unchanged. The meter must never add a failure mode to serving.
- **Captures per request:** timestamp, client label, upstream (model/endpoint/machine),
  request type (chat/completion/embeddings), streaming yes/no, prompt tokens, completion
  tokens, reasoning tokens, time-to-first-token, total latency, tokens/sec, HTTP status,
  error class (timeout/connection/upstream-5xx/ok), `finish_reason`. **No prompt/completion
  text in v1.**
- **Overhead budget:** target < ~20ms added latency; effectively zero on the streaming
  path (pure passthrough).

## Component 2 — The store (SQLite)

- One file on M1 (e.g. `~/ai/dashboard/telemetry.db`), **WAL mode** for concurrent
  readers + writers (meter writes requests, collectors write samples, dashboard reads).
- Tables (sketch):
  - `requests` — one row per call (all fields above).
  - `samples` — periodic hardware/health rows (machine, ts, mem fields, gpu?, thermal?,
    resident model, process RSS, endpoint up/down).
  - `events` — discrete events (launchd restart, endpoint down→up transitions).
  - `config` — frontier price rates for cost-avoided, client-key registry, retention.
- Retention: rolling window (e.g. raw rows 30–90 days, configurable) with optional
  pre-aggregated daily rollups for long-term trend panels. Keeps the file small and the
  dashboard fast.

## Component 3 — The collectors (hardware & health)

**Plain English:** a tiny script on each Mac that takes a "vital signs" reading every few
seconds.

- One TypeScript collector process per machine, launchd-managed. M1 writes to the SQLite
  file directly; **M2 POSTs its samples to a small ingest route** on M1 (it can't share the
  file across machines).
- **Capturable without elevated permission:** unified/physical memory pressure
  (`vm_stat`, `sysctl`), per-process RSS of the `mlx_lm.server` processes, which model is
  resident, load average, uptime, endpoint up/down (cheap `GET /models`), and launchd
  restart detection.
- **Needs `sudo` (optional elevated add-on):** GPU utilization % and temperature
  (`powermetrics`). Treated as a clearly-marked optional collector; v1 works fully without
  it, those panels just show "unavailable" until enabled.
- **Thunderbolt link health:** periodic latency/up check M1↔M2 (`ping`/endpoint RTT).

## Component 4 — The dashboard (Next.js + login)

**Plain English:** the website you actually look at.

- Next.js app on M1, bound to the LAN, behind a **simple login** (single account / shared
  password; lightweight — not full multi-user auth). Reads the SQLite file server-side.
- **Screens (mapped to the four priorities):**
  - **Overview:** live status of the 3 endpoints (up/down, in-flight, current tok/s),
    today's request count, today's cost-avoided, any active alerts.
  - **Performance:** tok/s over time per endpoint/model and per machine; time-to-first-token;
    end-to-end latency p50/p95; prompt vs generation tokens.
  - **Reliability:** error & timeout rate, slowest-requests table, failed-requests list,
    endpoint-uptime timeline, launchd restart events, Thunderbolt link health. *(This screen
    would have surfaced the `local_review` timeout immediately.)*
  - **Usage & attribution:** requests over time stacked by client; per-client and per-model
    tables; top consumers; **reasoning-tax** (reasoning vs content tokens per model).
  - **Hardware:** per-machine memory, GPU/thermal (if elevated collector on), resident
    model, process size.
  - **Cost-avoided:** cumulative $ saved vs frontier, by client and model, with editable
    rate assumptions.
  - **Request explorer:** filterable list of recent calls; click into one for its
    latency/token/status breakdown. Metadata only unless content capture is later enabled.
- **Live-ish updates:** poll the store on a short interval (simple, robust) rather than a
  socket layer in v1.

## The two novel panels (the differentiators)

- **Cost-avoided:** `tokens × configurable frontier $/Mtok` (separate input/output rates),
  summed cumulatively and per client/model. Directly measures the point of running local.
- **Reasoning-tax:** ratio of reasoning tokens to content tokens per model over time. Makes
  the hidden-thinking behavior (root cause of the `local_review` timeout) visible and
  watchable.

## Privacy & data captured

- v1 stores **metrics and metadata only** — never prompt or completion text. This sidesteps
  the sensitivity of health-adjacent data flowing from the peptides app.
- An **optional content-capture flag** (off by default) can be added later for trace
  drill-down, with redaction; explicitly out of v1 scope.
- The login keeps the LAN-exposed dashboard from being open to every device on the network.

## Rollout & safety

- The meter is **additive**: real model ports keep working, so nothing breaks on install.
- **Migrate one client at a time** by changing its base-URL port, lowest-stakes first
  (e.g. an MCP tool), validate against the dashboard, then move the rest. Instant revert by
  changing the port back. Same one-client-at-a-time discipline used for the repo
  consolidation.
- Fail-open meter guarantees monitoring can never take the models down.

## Phasing

- **Phase 1 — Core:** meter (with per-client keys + fail-open + streaming capture) →
  SQLite → Overview + Performance + Reliability screens. Migrate 1–2 clients. Proves the
  whole pipe end-to-end.
- **Phase 2 — Insight:** M1 + M2 hardware collectors, Usage/attribution screen,
  Cost-avoided screen. Migrate remaining clients.
- **Phase 3 — Polish:** alerts (timeout-rate / endpoint-down / memory-pressure
  thresholds), request explorer, reasoning-tax panel, visual refinement (frontend-design),
  optional elevated GPU/thermal collector.

## Testing strategy

- **Meter:** unit tests for fail-open (store down → request still forwarded), streaming
  passthrough, token/latency capture, client tagging, error classification. A soak test to
  confirm it adds no instability under sustained calls.
- **Collectors:** unit tests for parsers (`vm_stat`/`sysctl` output → fields); M2→M1 ingest.
- **Dashboard:** component tests with a seeded mock-data mode (build panels without needing
  live traffic); a Playwright happy-path; an accessibility check on key screens.
- Nothing claims "done" without the meter's fail-open test passing — that's the safety
  guarantee the whole design rests on.

## Risks & edge cases

- **Meter is in the hot path.** Mitigated by fail-open + additive rollout + per-client
  migration. The fail-open test is the linchpin.
- **TTFT only meaningful on streaming responses;** non-stream calls record total latency +
  tok/s and mark TTFT N/A.
- **SQLite write concurrency:** WAL mode + short transactions + a single writer per process
  handle the volume; if it ever grows, Postgres-via-OrbStack is the documented upgrade path.
- **GPU%/thermal need `sudo`;** kept as an optional collector so v1 is fully functional
  without elevated rights.
- **Per-client keys require touching each consumer's config** (MCP env, peptides `.env`,
  etc.) — done incrementally during migration; unknown keys still recorded as `unknown`.
- **Reachability:** dashboard + meter must run on the M1/M2 network (local infra), never a
  cloud host — same constraint as the peptides local-model feature.
- **Clock/timestamps:** M2 samples timestamped on M1 at ingest (or NTP-synced) to avoid
  skew between machines.

## Where this lives

A new repo `local-ai-dashboard` (scaffolded with `launchpad new` at implementation time):
`/meter` (TS service), `/collector` (TS, runs on each Mac), `/web` (Next.js dashboard),
`/db` (SQLite schema + migrations), plus launchd plists. This design doc is committed to
`server-setup/plans/` as the planning home; the implementation plan follows.
