# Unified Model Observability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route GLM-5.2 + DeepSeek through the meter as metered providers, ingest the subscription CLIs' OpenTelemetry as reported usage, and wire OpenCode + MMR — so every model lands in one dashboard.

**Architecture:** Two ingestion paths into one SQLite DB (`~/ai/dashboard/telemetry.db`): the existing meter proxy gains remote upstreams (new ports 9004/9005, real key swapped in server-side, `/v1` path-normalized) for full-fidelity metered rows; a small loopback OTLP receiver (`otel-usage-bridge`) writes usage-only `reported` rows. A per-model price table drives cost. OpenCode points at the meter ports; MMR shells out to `opencode run`.

**Tech Stack:** Node 22 `node:sqlite`, TypeScript, `undici` (meter HTTP), Vitest; OpenCode `@ai-sdk/openai-compatible` providers; MMR YAML channels; stdlib launchd.

## Global Constraints

- Local-only: meter binds `127.0.0.1`; the OTLP receiver binds `127.0.0.1` (never `0.0.0.0`).
- Secrets live only in the meter's environment (1Password/launchpad); CLIs send routing **labels**, never keys.
- The real provider key must never appear in any DB row, captured content, `error_detail`, or log line.
- Reported (subscription-CLI) rows store usage only — `content = null`; prompt logging disabled at source + stripped at the bridge.
- Fail-open: telemetry/capture errors never alter a forwarded response; remote-retrieval/forward errors surface as real status (502), never faked success.
- GLM OpenAI-compatible model id is `glm-5.2` (not `glm-5.2[1m]`). DeepSeek base has **no** `/v1`. Verified facts live in the spec.
- DB migrations are additive + idempotent (ALTER guarded by `PRAGMA table_info`), matching `src/shared/schema.ts`.

Spec: `plans/2026-06-19-unified-observability-spec.md`.

---

## File structure

`local-ai-dashboard` (metered path + cost):
- `src/shared/types.ts` — extend `Upstream`/`Machine` unions; add `RequestRow.source`, `RequestRow.cost_usd`.
- `src/shared/schema.ts` — additive `source`/`cost_usd` columns.
- `src/shared/prices.ts` (new) + `prices.test.ts` — per-model price table + lookup.
- `src/meter/upstreams.ts` (+ test) — `UpstreamDef` gains `kind`/`apiKeyEnv`/`stripV1`; ports 9004/9005.
- `src/meter/redact.ts` (new) + test — header redaction.
- `src/meter/cost.ts` (new) + test — compute `cost_usd` from usage + price table.
- `src/meter/proxy.ts` (+ test) — outbound key injection on a fresh header set; `/v1` strip; cost+source on the row.
- `src/meter/server.ts` — read remote keys at startup (fail-fast); pass to proxy deps.
- `src/meter/sink.ts` — INSERT includes `source`, `cost_usd`.
- `src/otel-bridge/bridge.ts` (new) + test — loopback OTLP/HTTP receiver → normalized usage → reported row.
- `scripts/start-meter.sh` (dashboard repo) — wrap launch in `launchpad secrets run`.

`server-setup` (CLIs + docs):
- `configs/opencode/opencode.json.example` (new) — providers → meter ports.
- `configs/mmr/channels.example.yaml` (new) — opencode-glm / opencode-deepseek.
- `scripts/enable-cli-telemetry.sh` (new) — OTLP enablement (prompt logging off) for Claude Code/Gemini/Codex.
- `docs/dev-stack-models.md`, `docs/observability.md` (new); cross-links in `README.md`, `docs/OPERATIONS.md`.

---

## Phase 1 — Metered remote upstreams (smallest shippable slice)

### Task 1: Types — unions + source/cost_usd

**Files:** Modify `src/shared/types.ts`; Test `src/shared/types.test.ts` (if absent, assert via schema test).

**Produces:** `Upstream` includes `'glm' | 'deepseek'`; `Machine` includes `'remote'`; `RequestRow.source: 'metered' | 'reported'`; `RequestRow.cost_usd: number | null`.

- [ ] Step 1: edit unions + interface:
```ts
export type Upstream = 'orchestrator' | 'developer' | 'reviewer' | 'glm' | 'deepseek';
export type Machine = 'm1' | 'm2' | 'remote';
export type RequestSource = 'metered' | 'reported';
// in RequestRow, after parent_id:
  source: RequestSource;
  cost_usd: number | null;
```
- [ ] Step 2: `npm run typecheck` — expect errors in proxy/sink/upstreams referencing the new required fields (fixed in later tasks). Commit after Task 3 when the tree typechecks.

### Task 2: Schema — additive columns

**Files:** Modify `src/shared/schema.ts`; Test `src/shared/schema.test.ts`.

- [ ] Step 1 (test): assert a migrated DB has `source` + `cost_usd` columns and existing rows default `source='metered'`.
```ts
it('adds source + cost_usd, defaulting source to metered', () => {
  const db = freshDb(); migrate(db);
  const cols = (db.prepare('PRAGMA table_info(requests)').all() as {name:string}[]).map(c=>c.name);
  expect(cols).toContain('source'); expect(cols).toContain('cost_usd');
});
```
- [ ] Step 2: run → FAIL.
- [ ] Step 3: in `migrate()`, in the CREATE TABLE add `source TEXT NOT NULL DEFAULT 'metered'` and `cost_usd REAL`; add ALTER guards:
```ts
if (!requestCols.includes('source')) db.exec("ALTER TABLE requests ADD COLUMN source TEXT NOT NULL DEFAULT 'metered'");
if (!requestCols.includes('cost_usd')) db.exec('ALTER TABLE requests ADD COLUMN cost_usd REAL');
```
- [ ] Step 4: run → PASS. Step 5: commit `feat(meter): source + cost_usd columns (additive)`.

### Task 3: Price table

**Files:** Create `src/shared/prices.ts` + `prices.test.ts`.

**Produces:** `priceFor(model: string): ModelPrice | null` where `ModelPrice = { input:number; cachedInput:number; output:number; billing:'metered'|'subscription' }` (USD per 1M tokens).

- [ ] Step 1 (test):
```ts
expect(priceFor('deepseek-v4-flash')).toEqual({ input:0.14, cachedInput:0.0028, output:0.28, billing:'metered' });
expect(priceFor('glm-5.2')?.billing).toBe('subscription');
expect(priceFor('unknown-model')).toBeNull();
```
- [ ] Step 2: FAIL. Step 3: implement the table (deepseek-v4-flash/pro, glm-5.2 subscription) + case-insensitive lookup. Step 4: PASS. Step 5: commit `feat(meter): per-model price table`.

### Task 4: Header redaction helper

**Files:** Create `src/meter/redact.ts` + `redact.test.ts`.

**Produces:** `redactHeaders(h: Record<string,string>): Record<string,string>` masking `authorization`/`proxy-authorization` (case-insensitive) to `'***'`.

- [ ] Step 1 (test): `expect(redactHeaders({Authorization:'Bearer sk-x'}).Authorization).toBe('***')`. Step 2: FAIL. Step 3: implement. Step 4: PASS. Step 5: commit.

### Task 5: Remote upstream defs + key/path handling

**Files:** Modify `src/meter/upstreams.ts` + test.

**Consumes:** types from Task 1. **Produces:** `UpstreamDef` gains `kind:'local'|'remote'`, `apiKeyEnv?:string`, `stripV1?:boolean`; `PORT_MAP` adds 9004/9005; new `outboundPath(path, def)` → strips a single leading `/v1` iff `def.stripV1`.

- [ ] Step 1 (test):
```ts
expect(upstreamForPort(9005).target).toBe('https://api.deepseek.com');
expect(upstreamForPort(9004).apiKeyEnv).toBe('ZAI_API_KEY');
expect(outboundPath('/v1/chat/completions', upstreamForPort(9005))).toBe('/chat/completions');
expect(outboundPath('/v1/models', upstreamForPort(9002))).toBe('/v1/models'); // local untouched
```
- [ ] Step 2: FAIL. Step 3: implement defs (9004 `https://api.z.ai/api/coding/paas/v4` ZAI_API_KEY stripV1; 9005 `https://api.deepseek.com` DEEPSEEK_API_KEY stripV1; existing three `kind:'local'`) + `outboundPath`. Step 4: PASS. Step 5: commit.

### Task 6: Proxy — outbound key injection + path strip + source/cost

**Files:** Modify `src/meter/proxy.ts` + `proxy.test.ts`.

**Consumes:** `outboundPath`, `redactHeaders`, `priceFor`, `computeCost` (Task 7 — write Task 7 first if executing strictly; here cost is folded into the row build). **Behavior:** build a fresh `outHeaders` for undici; if `upstream.apiKey` present set `outHeaders.authorization = 'Bearer '+key`; forward to `upstream.target + outboundPath(path, upstream)`; set `row.source` (`'metered'`), `row.cost_usd` (from `computeCost`). The inbound header set used for `clientForKey`/capture is never mutated.

- [ ] Step 1 (test, fake remote upstream): start an in-process HTTP server as the "remote"; configure a `ProxyDeps.upstream` with `apiKey:'real-secret'`, `stripV1:true`; POST `/v1/chat/completions` with `Authorization: Bearer mylabel`; assert the fake server received `Authorization: Bearer real-secret` and path `/chat/completions`; assert the recorded row + any error_detail never contain `real-secret`.
- [ ] Step 2: FAIL. Step 3: implement (see Behavior). Inject `apiKey` via `ProxyDeps` (resolved in server.ts). Step 4: PASS + existing proxy tests stay green. Step 5: commit `feat(meter): remote key injection + path-norm, key never logged`.

### Task 7: Cost computation

**Files:** Create `src/meter/cost.ts` + `cost.test.ts`.

**Produces:** `computeCost(model:string, prompt_tokens:number|null, completion_tokens:number|null): number|null` — null for unknown or `billing:'subscription'` models; else `(prompt/1e6*input)+(completion/1e6*output)`.

- [ ] Step 1 (test): `computeCost('deepseek-v4-flash',1_000_000,1_000_000)===0.42`; `computeCost('glm-5.2',...)===null`. Step 2: FAIL. Step 3: implement using `priceFor`. Step 4: PASS. Step 5: commit. (Wire into proxy row build in Task 6.)

### Task 8: Sink + server wiring

**Files:** Modify `src/meter/sink.ts` (INSERT adds `source`,`cost_usd`); `src/meter/server.ts` (read `process.env[apiKeyEnv]` for each remote port at startup → fail-fast with clear message if missing; pass `apiKey` into `ProxyDeps`).

- [ ] Step 1: update INSERT column list + bound params; add server startup key resolution + a unit/integration test that a configured remote port with no env key throws a clear error at startup. Step 2–4: tests green. Step 5: commit `feat(meter): persist source/cost; fail-fast on missing remote key`.

### Task 9: Secret injection at launch

**Files:** Modify `scripts/start-meter.sh` (dashboard repo).

- [ ] Wrap the node invocation in `launchpad secrets run --` (or `op run`) so `ZAI_API_KEY`/`DEEPSEEK_API_KEY` are present in the meter env; document `launchpad secrets set ZAI_API_KEY` / `DEEPSEEK_API_KEY`. (No unit test; verified live once keys exist.) Commit.

**Phase 1 acceptance:** full meter test suite green; with keys set, `curl :9005/v1/chat/completions` (deepseek-v4-flash) returns 200 and a `metered` row with `cost_usd>0`; the real key never appears in the DB/logs (asserted by Task 6 test).

---

## Phase 2 — Dashboard cost + source UI

### Task 10: Surface cost + source

**Files:** dashboard query/components (follow existing patterns in `apps/web`); Test alongside.

- [ ] Add `cost_usd` sum per model/day/month and a `source` tag to the request views; metered models show `$`, subscription (`glm-5.2`) shows token volume (cost null), reported rows tagged "usage only — no content". TDD the query aggregation; snapshot/RTL the component. Commit `feat(dashboard): cost + source surfacing`.

---

## Phase 3 — OpenCode + MMR

### Task 11: OpenCode provider config

**Files:** Create `configs/opencode/opencode.json.example` (server-setup).

- [ ] Providers `local-dev/-review/-orch` → `127.0.0.1:9002/9003/9001/v1`, `glm` → `:9004/v1` (model `glm-5.2`, `limit.context:1000000`), `deepseek` → `:9005/v1` (`deepseek-v4-pro`,`-flash`); every `apiKey:"opencode"` (label). Document copying to `~/.config/opencode/opencode.json` and resolving local model ids from `/v1/models`. Validate `opencode run --model deepseek/deepseek-v4-flash "hi"` once keys exist. Commit.

### Task 12: MMR channels

**Files:** Create `configs/mmr/channels.example.yaml`.

- [ ] `opencode-glm` (`command: opencode run`, `flags:["--model","glm/glm-5.2","--format","default"]`, `parser: default`) and `opencode-deepseek` (`deepseek/deepseek-v4-pro`). Document merging into `.mmr.yaml` / global config + `mmr review --channels opencode-glm opencode-deepseek`. Commit.

---

## Phase 4 — OTEL reported path

### Task 13: otel-usage-bridge

**Files:** Create `src/otel-bridge/bridge.ts` + `bridge.test.ts` (dashboard).

**Produces:** an OTLP/HTTP receiver bound `127.0.0.1:4318` parsing `/v1/metrics` + `/v1/logs`, mapping each CLI's token/cost metric to `{source:'reported', client, model, prompt_tokens, completion_tokens, cost_usd?, ts}` and writing a row with `content=null`. Strips any `prompt`/`gen_ai.input.messages`/`gen_ai.output.messages` field before write/log.

- [ ] Step 1 (test): feed an OTLP-shaped payload that includes a `prompt` field; assert the written row has `content` null and the bridge bound loopback. Step 2: FAIL. Step 3: implement (use `@opentelemetry/otlp-transformer` or a minimal JSON path for the metrics we map). Step 4: PASS. Step 5: commit.

### Task 14: ingest reported events + enable script

**Files:** Modify `src/meter/ingest.ts` (accept the reported event shape → row, `source='reported'`); Create `scripts/enable-cli-telemetry.sh` (server-setup).

- [ ] Ingest test: a reported event → one `source='reported'` row, content null. Enable script writes Claude Code (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, OTLP→`127.0.0.1:4318`), Gemini (`.gemini/settings.json`: enabled, target local, `GEMINI_TELEMETRY_LOG_PROMPTS=false`, traces off), Codex (`~/.codex/config.toml` `[otel]` otlp-http→loopback, `log_user_prompt=false`). Commit.

---

## Phase 5 — Ship

### Task 15: Docs + final

**Files:** `docs/dev-stack-models.md`, `docs/observability.md`; cross-links `README.md`, `docs/OPERATIONS.md`; `configs/env.machine1.example` secret-name notes.

- [ ] Write docs (metered-vs-reported model; what's captured; OpenCode/MMR usage; OTEL enablement). Run full test suites in both repos. Commit + push both. Note in the PR/commit what requires the user's ZAI_API_KEY/DEEPSEEK_API_KEY to activate live.

---

## Self-review notes

- Spec coverage: meter remote (Comp A → T1,5,6,8,9), cost+source (Comp B → T2,3,7,10), OpenCode (Comp C → T11), MMR (Comp D → T12), OTEL bridge (Comp E → T13,14), secrets (Comp F → T9), docs (T15). All five P1 review fixes carried: key-never-logged (T4,T6), loopback bridge (T13), `glm-5.2` id (T11,T12,prices), real receiver not stock collector (T13), prompt-logging off + strip (T13,T14).
- Type consistency: `source`/`cost_usd` defined in T1, used identically in T2/T6/T8/T10/T14; `priceFor`/`computeCost`/`outboundPath`/`redactHeaders` names stable across tasks.
- Keys-absent reality: every task is unit/integration-testable with fakes; only the live smokes (T9 acceptance, T11/T12 validation) need the user's API keys.
