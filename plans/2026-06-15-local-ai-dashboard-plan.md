# Local AI Stack Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LAN-accessible web dashboard that monitors all activity on the two-Mac local model stack (speed, reliability, who's using it, hardware, and cost-avoided), fed by a fail-open observing proxy.

**Architecture:** A TypeScript "meter" proxy sits in front of the three `mlx_lm.server` endpoints and records one row per request to a SQLite file without ever blocking serving. Lightweight collectors on each Mac POST hardware/health samples to the meter (the meter is the **sole DB writer**). A Next.js dashboard reads the SQLite file and renders the panels behind a login.

**Tech Stack:** TypeScript everywhere. Meter + collectors: Node 20+, `node:http`, `undici`, `better-sqlite3`, `vitest`. Dashboard: Next.js (App Router), React, `better-sqlite3` (read-only), Recharts, a minimal cookie-session login. launchd for process management.

**Design spec:** `plans/2026-06-15-local-ai-dashboard-design.md` (read it first).

---

## Scope note

One coherent system delivered in three phases. **Phase 1 tasks are fully specified** (it contains the only ops-critical, hard-to-reverse component — the meter — so it gets TDD rigor). Phases 2–3 are specified as ordered task breakdowns; expand each into bite-sized TDD steps once Phase 1 has landed and the real schema/log shapes are confirmed. Do not pre-code Phase 3 UI against a meter that doesn't exist yet (YAGNI).

## Repository & file structure

New repo `local-ai-dashboard` (scaffold with `launchpad new` → web template, then add the workspaces). pnpm workspace with three packages + shared:

```
local-ai-dashboard/
  packages/
    shared/        # types + SQLite schema/migrations shared by meter & web
      src/schema.ts        # table DDL + the migration runner
      src/types.ts         # RequestRow, SampleRow, EventRow, ClientLabel, Upstream
      src/cost.ts          # cost-avoided math (pure, unit-tested)
    meter/         # the proxy + ingest endpoint (sole DB writer) — runs on M1
      src/upstreams.ts     # port→upstream map + client-key registry
      src/record.ts        # async, fail-open recorder (queue → SQLite)
      src/proxy.ts         # streaming passthrough + capture
      src/ingest.ts        # POST /ingest for collector samples
      src/server.ts        # wires proxy ports + ingest; entrypoint
    collector/     # hardware/health sampler — runs on BOTH Macs
      src/mac-metrics.ts   # vm_stat/sysctl/ps parsers (pure functions)
      src/endpoints.ts     # endpoint up/down + Thunderbolt RTT checks
      src/main.ts          # sample loop → POST to meter /ingest
  apps/
    web/           # Next.js dashboard (read-only) — runs on M1
      app/…                # screens; lib/db.ts read-only SQLite; lib/auth.ts
  ops/
    launchd/             # plist templates: meter, collector-m1, collector-m2
    migrate-client.md    # the one-at-a-time base-URL cutover runbook
  pnpm-workspace.yaml
```

**Sole-writer rule:** only `meter` opens SQLite for writing. `collector` never touches the DB directly — it POSTs to `meter`'s `/ingest`. `web` opens SQLite **read-only**. This keeps SQLite to one writer and removes all multi-writer hazard.

---

# Phase 1 — Core pipe (meter → store → Overview/Performance/Reliability)

### Task 1: Scaffold workspace + shared schema

**Files:**
- Create: `pnpm-workspace.yaml`, `packages/shared/src/types.ts`, `packages/shared/src/schema.ts`, `packages/shared/src/schema.test.ts`

- [ ] **Step 1: Write the failing test** for the migration runner

```ts
// packages/shared/src/schema.test.ts
import { describe, it, expect } from 'vitest';
import Database from 'better-sqlite3';
import { migrate } from './schema';

describe('migrate', () => {
  it('creates requests/samples/events/config tables and is idempotent', () => {
    const db = new Database(':memory:');
    migrate(db);
    migrate(db); // second run must not throw
    const names = db.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).all().map((r: any) => r.name);
    expect(names).toEqual(expect.arrayContaining(['config', 'events', 'requests', 'samples']));
  });
});
```

- [ ] **Step 2: Run it, confirm it fails** — `pnpm --filter shared test` → FAIL (`migrate` not defined).

- [ ] **Step 3: Implement types + schema**

```ts
// packages/shared/src/types.ts
export type Upstream = 'orchestrator' | 'developer' | 'reviewer';
export type ClientLabel = string; // 'claude-code' | 'codex' | 'antigravity' | 'peptides' | 'mcp-local-review' | 'mcp-run-plan' | 'unknown'
export interface RequestRow {
  id?: number; ts: number; client: ClientLabel; upstream: Upstream; machine: 'm1' | 'm2';
  model: string; kind: 'chat' | 'completion' | 'embeddings' | 'other'; streamed: 0 | 1;
  prompt_tokens: number | null; completion_tokens: number | null; reasoning_tokens: number | null;
  ttft_ms: number | null; latency_ms: number; tokens_per_sec: number | null;
  status: number; error_class: 'ok' | 'timeout' | 'connection' | 'upstream_5xx' | 'other'; finish_reason: string | null;
}
export interface SampleRow {
  id?: number; ts: number; machine: 'm1' | 'm2'; mem_used_mb: number; mem_pressure_pct: number;
  proc_rss_mb: number | null; resident_model: string | null; load_avg: number | null;
  gpu_pct: number | null; thermal_c: number | null; endpoints_up: number; tb_rtt_ms: number | null;
}
export interface EventRow { id?: number; ts: number; kind: 'launchd_restart' | 'endpoint_down' | 'endpoint_up'; detail: string; }
```

```ts
// packages/shared/src/schema.ts
import type Database from 'better-sqlite3';
export function migrate(db: Database.Database): void {
  db.pragma('journal_mode = WAL');
  db.exec(`
    CREATE TABLE IF NOT EXISTS requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, client TEXT NOT NULL,
      upstream TEXT NOT NULL, machine TEXT NOT NULL, model TEXT NOT NULL, kind TEXT NOT NULL,
      streamed INTEGER NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER, reasoning_tokens INTEGER,
      ttft_ms INTEGER, latency_ms INTEGER NOT NULL, tokens_per_sec REAL,
      status INTEGER NOT NULL, error_class TEXT NOT NULL, finish_reason TEXT);
    CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);
    CREATE INDEX IF NOT EXISTS idx_requests_client ON requests(client);
    CREATE TABLE IF NOT EXISTS samples (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, machine TEXT NOT NULL,
      mem_used_mb REAL, mem_pressure_pct REAL, proc_rss_mb REAL, resident_model TEXT,
      load_avg REAL, gpu_pct REAL, thermal_c REAL, endpoints_up INTEGER, tb_rtt_ms REAL);
    CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, kind TEXT NOT NULL, detail TEXT);
    CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
  `);
}
```

- [ ] **Step 4: Run the test, confirm PASS.**
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(shared): SQLite schema + migration runner"`

### Task 2: Upstream map + client-key registry

**Files:** Create `packages/meter/src/upstreams.ts`, `packages/meter/src/upstreams.test.ts`

- [ ] **Step 1: Failing test**

```ts
import { describe, it, expect } from 'vitest';
import { upstreamForPort, clientForKey } from './upstreams';
describe('upstreams', () => {
  it('maps listen port to the correct upstream', () => {
    expect(upstreamForPort(9001).name).toBe('orchestrator');
    expect(upstreamForPort(9002).target).toBe('http://10.10.10.2:8002');
    expect(upstreamForPort(9003).machine).toBe('m2');
  });
  it('labels known keys and falls back to unknown', () => {
    expect(clientForKey('codex')).toBe('codex');
    expect(clientForKey('mystery-xyz')).toBe('unknown');
    expect(clientForKey(undefined)).toBe('unknown');
  });
});
```

- [ ] **Step 2: Run, confirm FAIL.**
- [ ] **Step 3: Implement**

```ts
// packages/meter/src/upstreams.ts
import type { Upstream } from 'shared/src/types';
export interface UpstreamDef { name: Upstream; target: string; machine: 'm1' | 'm2'; }
const PORT_MAP: Record<number, UpstreamDef> = {
  9001: { name: 'orchestrator', target: 'http://127.0.0.1:8001', machine: 'm1' },
  9002: { name: 'developer', target: 'http://10.10.10.2:8002', machine: 'm2' },
  9003: { name: 'reviewer', target: 'http://10.10.10.2:8003', machine: 'm2' },
};
export function upstreamForPort(port: number): UpstreamDef {
  const u = PORT_MAP[port];
  if (!u) throw new Error(`no upstream for port ${port}`);
  return u;
}
const KNOWN = new Set(['claude-code', 'codex', 'antigravity', 'peptides', 'mcp-local-review', 'mcp-run-plan']);
export function clientForKey(key: string | undefined): string {
  if (key && KNOWN.has(key)) return key;
  return 'unknown';
}
```

- [ ] **Step 4: Run, confirm PASS.**
- [ ] **Step 5: Commit** — `git commit -am "feat(meter): upstream map + client-key registry"`

### Task 3: Fail-open async recorder (the safety linchpin)

**Files:** Create `packages/meter/src/record.ts`, `packages/meter/src/record.test.ts`

- [ ] **Step 1: Failing tests** — the two guarantees that make this whole project safe to deploy:

```ts
import { describe, it, expect, vi } from 'vitest';
import { createRecorder } from './record';
import type { RequestRow } from 'shared/src/types';

const row: RequestRow = { ts: 1, client: 'codex', upstream: 'orchestrator', machine: 'm1',
  model: 'm', kind: 'chat', streamed: 0, prompt_tokens: 10, completion_tokens: 5, reasoning_tokens: 0,
  ttft_ms: null, latency_ms: 100, tokens_per_sec: 50, status: 200, error_class: 'ok', finish_reason: 'stop' };

describe('recorder (fail-open)', () => {
  it('record() never throws even if the sink throws', () => {
    const rec = createRecorder({ insert: () => { throw new Error('db down'); } });
    expect(() => rec.record(row)).not.toThrow();   // MUST be true — serving must never break
  });
  it('record() returns synchronously without awaiting the write', () => {
    let wrote = false;
    const rec = createRecorder({ insert: () => { wrote = true; } });
    rec.record(row);
    expect(wrote).toBe(false); // deferred; flushed on next tick, not in the request path
  });
  it('flushes queued rows to the sink', async () => {
    const seen: RequestRow[] = [];
    const rec = createRecorder({ insert: (r) => seen.push(r) });
    rec.record(row);
    await rec.flush();
    expect(seen).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run, confirm FAIL.**
- [ ] **Step 3: Implement** a queue that defers writes and swallows all errors

```ts
// packages/meter/src/record.ts
import type { RequestRow } from 'shared/src/types';
export interface Sink { insert: (r: RequestRow) => void; }
export function createRecorder(sink: Sink) {
  const queue: RequestRow[] = [];
  let scheduled = false;
  function drain() {
    scheduled = false;
    const batch = queue.splice(0, queue.length);
    for (const r of batch) { try { sink.insert(r); } catch { /* fail-open: drop, never surface */ } }
  }
  return {
    record(r: RequestRow) {
      try { queue.push(r); if (!scheduled) { scheduled = true; setImmediate(drain); } }
      catch { /* even enqueue must never throw into the request path */ }
    },
    async flush() { drain(); },
  };
}
```

- [ ] **Step 4: Run, confirm PASS.**
- [ ] **Step 5: Commit** — `git commit -am "feat(meter): fail-open async recorder"`

### Task 4: Token/latency/error extraction from upstream responses

**Files:** Create `packages/meter/src/capture.ts`, `packages/meter/src/capture.test.ts`

- [ ] **Step 1: Failing tests** covering non-stream usage, the reasoning split, and error classification

```ts
import { describe, it, expect } from 'vitest';
import { parseUsage, classifyError, tokensPerSec } from './capture';
describe('capture', () => {
  it('reads token counts incl. reasoning from a non-stream body', () => {
    const body = { usage: { prompt_tokens: 12, completion_tokens: 30, completion_tokens_details: { reasoning_tokens: 20 } },
      choices: [{ finish_reason: 'stop' }] };
    const u = parseUsage(body);
    expect(u.prompt_tokens).toBe(12);
    expect(u.completion_tokens).toBe(30);
    expect(u.reasoning_tokens).toBe(20);
    expect(u.finish_reason).toBe('stop');
  });
  it('classifies errors', () => {
    expect(classifyError(200, null)).toBe('ok');
    expect(classifyError(0, new Error('ETIMEDOUT'))).toBe('timeout');
    expect(classifyError(0, new Error('ECONNREFUSED'))).toBe('connection');
    expect(classifyError(503, null)).toBe('upstream_5xx');
  });
  it('computes tokens/sec', () => { expect(tokensPerSec(100, 2000)).toBe(50); });
});
```

- [ ] **Step 2: Run, confirm FAIL.**
- [ ] **Step 3: Implement** `parseUsage`, `classifyError`, `tokensPerSec` (pure functions; tolerate missing fields by returning nulls).
- [ ] **Step 4: Run, confirm PASS.**
- [ ] **Step 5: Commit** — `git commit -am "feat(meter): response capture helpers"`

### Task 5: Streaming-safe proxy handler

**Files:** Create `packages/meter/src/proxy.ts`, `packages/meter/src/proxy.test.ts`

- [ ] **Step 1: Failing integration test** — spin a fake upstream `http` server; assert the proxy returns its bytes unchanged AND records a row. Cover both a JSON response and an SSE stream. Critically assert: **when the recorder is wired to a throwing sink, the proxied response is still correct** (fail-open at the handler level).

```ts
// Pseudostructure — write it concretely against node:http test servers.
// 1. start fake upstream returning {"usage":{...},"choices":[{"finish_reason":"stop"}]}
// 2. start proxy pointing at it with a recorder spy
// 3. client GET/POST through proxy → body bytes equal upstream's; one row recorded with correct tokens/latency/client
// 4. repeat with sink that throws → response STILL equals upstream's (no 500)
// 5. SSE case: upstream streams 'data: {...}\n\n' chunks; proxy forwards chunk-for-chunk; ttft_ms recorded > 0
```

- [ ] **Step 2: Run, confirm FAIL.**
- [ ] **Step 3: Implement** with `node:http` + `undici`: read `Authorization`/api-key → `clientForKey`; record `t0`; forward method/headers/body to `upstreamForPort(listenPort).target + url`; on first upstream byte record `ttft_ms`; **pipe** the upstream stream straight to the client response while teeing a copy to a buffer/parser; on end, build the `RequestRow` and call `recorder.record(...)`. Wrap ALL capture/record logic in try/catch so a parsing failure can never corrupt the forwarded response. For non-stream, parse buffered JSON via `parseUsage`.
- [ ] **Step 4: Run, confirm PASS** (all cases, especially the throwing-sink case).
- [ ] **Step 5: Commit** — `git commit -am "feat(meter): streaming-safe fail-open proxy"`

### Task 6: SQLite sink + meter entrypoint + ingest route

**Files:** Create `packages/meter/src/ingest.ts`, `packages/meter/src/server.ts`, `packages/meter/src/sink.ts`, tests for sink + ingest

- [ ] **Step 1: Failing test** — `sink.insert(row)` persists to a temp SQLite and `/ingest` validates+inserts a `SampleRow`; a malformed ingest body returns 400 without throwing.
- [ ] **Step 2: Run, confirm FAIL.**
- [ ] **Step 3: Implement** `sink.ts` (better-sqlite3 prepared `INSERT` for requests; **the only writer**); `ingest.ts` (validate JSON sample → insert into `samples`/`events`); `server.ts` (run `migrate`; open one writable DB; start three `http` listeners on 9001/9002/9003 each bound to its proxy handler; start the ingest listener on a localhost+LAN port; graceful shutdown flushes the recorder).
- [ ] **Step 4: Run, confirm PASS.**
- [ ] **Step 5: Commit** — `git commit -am "feat(meter): sqlite sink, ingest route, server entrypoint"`

### Task 7: launchd for the meter + first real cutover

**Files:** Create `ops/launchd/com.localai.dashboard.meter.plist`, `ops/migrate-client.md`

- [ ] **Step 1:** Write the plist (RunAtLoad + KeepAlive, logs to `~/ai/logs/dashboard-meter.log`, runs `node packages/meter/dist/server.js`). Write `migrate-client.md`: the runbook to repoint ONE client's base URL from `:800x` to `:900x` and its api-key to its label, validate in the DB, and revert.
- [ ] **Step 2:** Load it: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.localai.dashboard.meter.plist`; confirm `launchctl print` shows running and `curl :9001/v1/models` proxies through.
- [ ] **Step 3: Cutover the lowest-stakes client first** — repoint `mcp-local-review` to `http://127.0.0.1:9001/v1` with api-key `mcp-local-review`. Run one real review; confirm a `requests` row appears with `client='mcp-local-review'`. **Verify against the DB, do not trust the absence of errors.**
- [ ] **Step 4: Commit** — `git commit -am "ops(meter): launchd unit + client cutover runbook"`

### Task 8: Dashboard skeleton + read-only DB + login + first three screens

**Files:** `apps/web/*` (Next.js), `apps/web/lib/db.ts`, `apps/web/lib/auth.ts`, screen routes + queries

- [ ] **Step 1:** Scaffold Next.js (App Router, TS). Add `lib/db.ts` opening SQLite **read-only** (`new Database(path, { readonly: true })`). Add `lib/auth.ts`: a single shared password (from env `DASHBOARD_PASSWORD`) → signed httpOnly cookie; middleware gates all routes; a `/login` page.
- [ ] **Step 2:** Write data-access functions with unit tests against a seeded temp DB: `getOverview()`, `getPerformanceSeries(range)`, `getReliability(range)` (error/timeout rate, slowest N, uptime from `events`).
- [ ] **Step 3:** Build the **Overview**, **Performance**, and **Reliability** screens with Recharts; a `?mock=1` seed mode so panels render without live traffic. Poll every few seconds for "live-ish".
- [ ] **Step 4:** Run it on the LAN (`next start -H 0.0.0.0`), log in from another device, confirm the cutover client's traffic shows up.
- [ ] **Step 5: Commit** — `git commit -am "feat(web): read-only dashboard, login, overview/performance/reliability"`

### Phase 1 acceptance
- Meter live under launchd; one real client cutover; `requests` rows landing with correct client/tokens/latency.
- Fail-open tests green (recorder + proxy throwing-sink cases) — the deploy-safety guarantee.
- Dashboard reachable on the LAN behind login, showing real Overview/Performance/Reliability.

---

# Phase 2 — Insight (attribution, hardware, cost-avoided)

Expand each into TDD steps at execution time.

### Task 9: Collector — Mac metrics parsers
Pure functions in `collector/src/mac-metrics.ts` that parse `vm_stat`, `sysctl hw.memsize`, and `ps` output into `mem_used_mb`/`mem_pressure_pct`/`proc_rss_mb`/`resident_model`/`load_avg`. Unit-test each parser against captured real command output (paste fixtures). No `sudo`.

### Task 10: Collector — endpoint/Thunderbolt health + main loop
`endpoints.ts`: `GET /models` up/down per endpoint + `ping`/RTT M1↔M2 → `endpoints_up`, `tb_rtt_ms`, and `endpoint_down/up` events. `main.ts`: every N seconds build a `SampleRow` and POST to meter `/ingest`. launchd units `com.localai.dashboard.collector` for M1 and M2 (M2 points `INGEST_URL` at M1's LAN IP).

### Task 11: Usage & attribution screen
Queries: requests over time stacked by `client`; per-client and per-model tables; top consumers; **reasoning-tax** = `sum(reasoning_tokens)/sum(completion_tokens)` per model over time. New screen with stacked charts. Migrate the remaining clients (`codex`, `claude-code`, `antigravity`, `peptides`, `mcp-run-plan`) one at a time per the runbook, verifying each appears.

### Task 12: Cost-avoided
`shared/src/cost.ts` (pure, unit-tested): `costAvoided(promptTok, completionTok, rates)` using editable `config` rates (input/output $/Mtok). Screen: cumulative + by client/model, with a rates editor writing to `config` (via a small authed write route on the meter — keep meter the sole writer).

### Phase 2 acceptance
Both collectors feeding samples; Hardware data visible; all clients attributed; Cost-avoided accumulating with editable rates.

---

# Phase 3 — Polish

### Task 13: Alerts
Threshold rules (timeout-rate, endpoint-down, memory-pressure) evaluated on a timer in the meter → `events`; dashboard banner + optional `launchpad notify` desktop push.

### Task 14: Request explorer
Filterable recent-requests table (client/model/status/time) with a drill-down (latency/token/status breakdown). Metadata only. (If content capture is ever wanted, add an opt-in `LOG_CONTENT` flag to the meter + redaction — explicitly deferred.)

### Task 15: Hardware screen + optional elevated collector
Per-machine memory/model/RSS panels. Optional `sudo`-elevated collector variant adding `gpu_pct`/`thermal_c` via `powermetrics`; panels show "unavailable" until enabled.

### Task 16: Visual pass
Apply `frontend-design` + `web-design-guidelines`; accessibility check on key screens; visual-regression snapshots.

### Phase 3 acceptance
Alerts fire on a forced condition; explorer usable; hardware (and optional GPU/thermal) shown; UI passes the design + a11y review.

---

## Self-review (spec coverage)

- Meter / fail-open / streaming / attribution / capture → Tasks 2–7. ✓
- SQLite store + sole-writer rule → Tasks 1, 6 (writer), 8 (read-only reader). ✓
- Collectors (M1+M2, no-sudo + optional sudo) → Tasks 9, 10, 15. ✓
- Four screens + 2 novel panels (cost-avoided, reasoning-tax) → Tasks 8, 11, 12, 15. ✓
- LAN + login → Task 8. ✓ Metrics-only default → schema has no content column; content deferred in Task 14. ✓
- Additive, one-at-a-time rollout → Tasks 7, 11 + `ops/migrate-client.md`. ✓
- Testing (fail-open linchpin, parsers, seeded UI) → Tasks 3, 5, 9, 8. ✓
- Phasing matches the spec's v1/v2/v3. ✓

No placeholders in Phase 1 tasks; Phases 2–3 are intentionally task-level (expand at execution, after Phase 1 confirms schema/log shapes).
