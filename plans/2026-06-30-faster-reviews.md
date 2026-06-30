# Plan: Faster Reviews (optimize + M1 overflow)

Status: **IMPLEMENTED 2026-06-30** (approved via /goal). Summary of what shipped:
- **A (titles off the reviewer):** OpenCode `small_model: glm-meter/glm-5.2` — title/summary generation
  no longer hits the local reviewer. Verifiable on the dashboard as new sessions run.
- **B (lean reviews):** OpenCode `review` agent (tools disabled) cut review prompts **~27.5k → 11.6k
  tokens (~58%)** with good verdict quality (caught a planted bug); MMR `opencode-local` uses
  `--agent review` and routes via the `:9006` review router.
- **C (concurrency cap):** meter caps the reviewer at `METER_REVIEWER_MAX_INFLIGHT` (default 2)
  concurrent completions; trivial calls (`/models`) bypass it.
- **D (M1 overflow router):** meter `:9006` prefers the reviewer, spills to a healthy idle M1
  orchestrator. **BLOCKER:** M1's orchestrator currently HANGS on `/chat/completions` (answers
  `/models` only), so overflow is health-gated OFF until it serves again — reviews safely queue on the
  reviewer meanwhile. Set `METER_ORCH_REVIEW_MODEL` to M1's served id once the orchestrator is fixed.

Direction chosen by user: **"Optimize + M1 overflow."**

## Goal

Cut the wall-clock time of local code reviews (currently ~163s avg, ~2.9 tok/s) by removing wasted
load, shrinking review prompts, capping concurrency so M2 stops thrashing, and spilling overflow
reviews onto M1's idle orchestrator — without degrading review quality or harming M1's daily-driver
responsiveness.

## Non-goals

- Not changing the two-machine architecture (M1 control plane + M2 worker). M1 stays the daily driver.
- Not replacing the review models or retraining/quantizing them.
- Not touching the GLM/DeepSeek remote paths or the metered/reported telemetry model.
- Not building a general-purpose load balancer for all endpoints — scope is the **review** path only.

## Current system summary (measured 2026-06-29/30)

- `reviewer` (M2 `:8003`, `reviewer-llmfan46-qwen36-27b`) and `developer` (M2 `:8002`,
  `developer-qwen36-27b-heretic2-mixed94`) are **both 27B on the same Mac Studio**. `orchestrator`
  (M1 `:8001`) is a **35B BF16**, fast and **nearly idle** (2 req/24h).
- Reviewer slowness is **not the model or endpoint** — it's workload:
  - When the reviewer gets a small prompt it runs at **11.6 tok/s (identical to developer)**.
  - Real reviews send **~27k-token prompts** (full `opencode` agent context) → ~2.9 tok/s, ~277s each.
  - **Up to 7 reviews run concurrently** (avg 2.2 in-flight) on one Mac Studio → memory-bandwidth
    thrash makes each slower.
- **~36% of reviewer requests are pure housekeeping**: 152/24h are OpenCode **"title generator"**
  calls that ship the *entire conversation* (~40k tokens) to the 27B just to produce a 50-char title.
  OpenCode has **no `small_model` configured**, so titles/summaries fall back to the slow agent model.
- The meter (`local-ai-dashboard/src/meter`) is **port→fixed-upstream** (`PORT_MAP` in `upstreams.ts`);
  `proxy.ts` forwards each request with a single `undiciRequest` and has **no concurrency limiting and
  no routing**. mlx_lm.server serves whatever model it loaded; the request `model` field is currently
  *decorative* (developer requests carry the `llmfan46` id but the server serves `mixed94`).

## Proposed architecture

Four workstreams, sequenced cheapest-highest-impact first, **measuring on the dashboard between each**:

- **A. Offload OpenCode housekeeping off the reviewer** (config only). Set OpenCode `small_model` so
  title/summary generation stops hitting the local 27B with full-conversation context.
- **B. Lean review invocation** (MMR/OpenCode config). Stop running reviews as full `opencode run`
  agent sessions (27k context of tools+files); send a direct, minimal "review this diff" prompt.
- **C. Per-upstream concurrency cap in the meter** (code). A small in-flight semaphore so the reviewer
  runs ≤N concurrent decodes instead of 7; excess queues. Prevents self-inflicted thrash.
- **D. M1 overflow router for reviews** (code). A new virtual `review` upstream that prefers M2's
  reviewer but spills to M1's orchestrator when the reviewer is at its cap **and** M1 is idle.

```
 MMR / OpenCode review ─┐
                        │   meter :9006 "review router"
                        └──▶  in-flight(reviewer) < CAP  ──▶ M2 :8003 (reviewer 27B)   [preferred]
                              else, and M1 load < LIMIT  ──▶ M1 :8001 (orchestrator 35B) [overflow]
                              else queue for reviewer
 titles/summaries ────────▶  small_model (fast: GLM or disabled)        [off the reviewer entirely]
```

## Files expected to change

- `~/.config/opencode/opencode.json` + `server-setup/configs/opencode/opencode.json.example` — add
  `small_model`; (B) add a lean review provider/model or reduce agent context for reviews.
- `~/.mmr/config.yaml` (+ `server-setup/configs/mmr/channels.example.yaml`) — point the
  `opencode-local` review channel at the lean review path / the new `review` router port.
- `local-ai-dashboard/src/meter/upstreams.ts` — add the `review` virtual upstream (port `9006`) with a
  target *picker*; add an optional `maxInFlight` per `UpstreamDef`.
- `local-ai-dashboard/src/meter/proxy.ts` — per-upstream in-flight semaphore (C) + route selection +
  model-field rewrite when routing to M1 (D).
- `local-ai-dashboard/src/meter/inflight.ts` (NEW) — tiny in-flight counter/semaphore module (unit-tested).
- `local-ai-dashboard/src/meter/router.ts` (NEW) — `pickReviewTarget(inflight, m1Busy)` pure function (unit-tested).
- `local-ai-dashboard/src/meter/server.ts` — wire the new port; expose in-flight counts to the router.
- `server-setup/docs/dev-stack-models.md` + `docs/observability.md` — document the review router + caps.

## Step-by-step implementation tasks

### Phase A — Stop wasting the reviewer on titles/summaries (config; do first, measure)
1. Decide the `small_model` target (see Risks → privacy). Recommended: a **fast remote** for titles
   (cloud handles the 40k-token prefill in ~1–2s that no local Mac can) — e.g. `glm-meter/glm-5.2` —
   **or** disable OpenCode auto-title if privacy of conversation text to Z.ai is unwanted.
2. Add `"small_model": "<choice>"` to `~/.config/opencode/opencode.json` and the `.example`.
3. Restart/rerun OpenCode; trigger several sessions.
4. **Acceptance:** on the dashboard, reviewer requests whose prompt begins `You are a title generator`
   drop to ~0; reviewer 24h request count falls by roughly the title share; no new errors.

### Phase B — Lean review prompts (config)
1. Inspect what `opencode run` sends for a review (the 27k context = system prompt + tool schemas +
   file context). Confirm reviews don't need the full agent.
2. Change the `opencode-local` MMR channel to a **direct, minimal** review call (diff + rubric only),
   e.g. a dedicated lean provider/model or `opencode run` with tools/context disabled.
3. **Acceptance:** reviewer `avg_prompt_tokens` drops from ~27k toward ≤8k; `avg tok/s` rises toward
   the small-prompt baseline (~11 tok/s); review verdict quality unchanged on a 5-diff sample (MMR
   `--dry-run` + spot check).

### Phase C — Per-upstream concurrency cap (TDD)
1. `inflight.ts`: `class InFlight { acquire(name): release; count(name): number }` (Promise-queue
   semaphore, configurable max). Test: acquire beyond max queues; release drains FIFO.
2. `UpstreamDef.maxInFlight?: number`; set reviewer's cap (start `2`, env-overridable
   `METER_REVIEWER_MAX_INFLIGHT`).
3. `proxy.ts`: `const rel = await inflight.acquire(upstream.name)` before `undiciRequest`; `rel()` in
   `finally`. Test: a 3rd concurrent reviewer request waits until one finishes.
4. **Acceptance:** dashboard concurrency probe shows reviewer max-in-flight ≤ cap; per-request
   `avg tok/s` rises vs the 7-concurrent baseline; no requests dropped (queued, not 503).

### Phase D — M1 overflow router (TDD)
1. `router.ts`: `pickReviewTarget({reviewerInFlight, cap, m1InFlight, m1Limit}) → 'reviewer' | 'orchestrator' | 'queue'`
   pure function. Tests cover: under cap → reviewer; at cap & M1 free → orchestrator; at cap & M1 busy → queue.
2. Add `9006: { name: 'review', … , picker: true }` to `PORT_MAP`; `proxy.ts` resolves the real target
   via `pickReviewTarget` using live in-flight counts (reviewer from C; M1 from the collector's latest
   sample or a live probe).
3. **Model-field handling:** when routing to M1, rewrite the request `model` to M1's served id (verify
   whether mlx_lm.server rejects a mismatched `model`; if it ignores it, no rewrite needed — test both).
4. Point the `opencode-local` channel base URL at `…:9006/v1`.
5. **Acceptance:** under a burst of reviews, dashboard shows some `review` traffic served by
   `orchestrator` (M1) while reviewer is capped; total review wall-clock for a batch drops; M1 daily-
   driver latency stays acceptable (define a guardrail: skip M1 when its in-flight ≥ `m1Limit`, default 1).

## Acceptance criteria (overall, dashboard-measurable)

- Reviewer **avg tok/s ≥ ~8** (up from 3.7) and **avg latency well below 163s** for typical reviews.
- Title-generator traffic to the reviewer ≈ 0.
- No increase in real (non-throttle) error rate; no M1 daily-driver regression beyond the guardrail.
- Review output quality unchanged on a fixed 5-diff regression sample.

## Test plan

- Unit (vitest, in `local-ai-dashboard`): `inflight.test.ts`, `router.test.ts`; extend `proxy` tests
  for the semaphore + route selection + model rewrite. Keep the full suite green.
- Integration: drive a real `mmr review` burst; confirm via SQLite/telemetry the cap holds, overflow
  lands on M1, and tok/s improves. Use `--dry-run` first.
- Quality: rerun a fixed set of 5 diffs pre/post and diff the verdicts.

## Rollback plan

- A/B (config) revert by restoring the prior `opencode.json` / `~/.mmr/config.yaml` (keep backups).
- C/D (meter): gated by env — `METER_REVIEWER_MAX_INFLIGHT=0` disables the cap; pointing the channel
  back at `…:9003/v1` bypasses the `9006` router entirely. The meter runs via `tsx`, so revert =
  restore files + `launchctl kickstart -k …dashboard.meter`. No schema/data changes.

## Docs updates

- `docs/dev-stack-models.md`: the review router, the cap, the `small_model` offload, and the M1
  overflow guardrail.
- `docs/observability.md`: note the new `review` virtual endpoint in the meter port map.

## Risks & edge cases

- **Privacy (Phase A):** routing titles/summaries to GLM sends conversation text to Z.ai. If unwanted,
  disable OpenCode auto-title or use a small *local* model instead (slower prefill, but private).
- **M1 daily-driver contention (Phase D):** overflow must be conservative — hard guardrail
  `m1Limit=1` and skip M1 entirely if the user is actively using it (M1 in-flight > 0 from non-review
  clients). Prefer queueing on the reviewer over disturbing M1.
- **Model-field validation:** mlx_lm.server may reject a `model` that doesn't match what it loaded.
  Phase D step 3 must verify and rewrite if needed (the field already mismatches today without error,
  suggesting it's tolerant — confirm).
- **Quality drift:** the 35B orchestrator is a *different* (larger) reviewer than the 27B; verdicts may
  differ. Treat as acceptable (likely better) but verify on the regression sample.
- **Concurrency cap too low** could serialize reviews and *raise* batch wall-clock; tune `cap` (2–3)
  against measured throughput, don't hard-code blindly.
- **Throttle interaction:** GLM reviews already 429-throttle; if titles move to GLM, watch GLM load.
