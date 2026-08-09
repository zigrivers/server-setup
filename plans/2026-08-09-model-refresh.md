# 2026-08-09 — Model refresh (reviewer quant, DeepSeek V4, local GLM-5.2, new RAG embedder)

## Goal

Bring the two-Mac stack up to date after four months on the April-2026 Qwen3.6 checkpoints:
make the busiest endpoint faster at no quality cost, replace the slowest-per-token worker, bring
GLM in-house, and replace the 2023-era RAG embedder.

## Non-goals

- No change to the two-machine architecture, the meter, or the endpoint/port contract.
- No new paid services. No cloud fallbacks removed (z.ai and DeepSeek stay reachable).
- No abliteration/finetuning work; candidate models are used as published.

## Current system (measured 2026-08-09, before changes)

| Endpoint | Model | Quant | Disk | tok/s (24h avg) | Req/24h |
|---|---|---|---|---|---|
| orchestrator M1:8001 | Qwen3.6-35B-A3B heretic | bf16 | 65 GB | 34.9 | 1 |
| developer M2:8002 | Qwen3.6-27B heretic2 | 8-bit g32 | 30 GB | 11.7 | 1,380 |
| reviewer M2:8003 | Qwen3.6-27B heretic-v2 | bf16 | 50 GB | 6.0 | 1,595 |
| glm (meter :9004) | z.ai cloud glm-4.5…5.2 | — | — | 22.1 | 323 |
| RAG embedder | bge-small-en-v1.5 (2023) | bf16 | — | — | 9 collections, 134,640 chunks |

Hardware: 2× Mac15,14 (M3 Ultra), 512 GiB unified memory each, 8 TB volumes.
`iogpu.wired_limit_mb = 0` on both (macOS default ≈ 384 GB usable by the GPU).

## Moves

### 1. Reviewer → 8-bit — DONE

Same weights, the Developer's quantization recipe. 50 GB → 28 GB, 6.0 → **19.5 tok/s** measured on
an identical prompt. `REVIEW_MODEL_PATH` in `~/ai/local-ai-stack/.env` on M2 (backup: `.env.bak-20260809`).

Follow-on defect found and fixed: `mlx_lm.server` **loads whatever model id the client sends**, and
1,400+ requests/day arrive with the old HF repo id — those would have pulled the 51 GB BF16 out of
the HF cache and silently kept the slow path. The meter now pins each local endpoint to its served
weights (`forceModel` in `src/meter/upstreams.ts`, env `METER_REVIEW_MODEL` / `METER_DEV_MODEL`).
Verified: a request carrying the stale id is served by the q8 path.

### 2. Developer → DeepSeek-V4-Flash — BLOCKED (needs a decision)

284B/13B-active MoE, MIT, 1M context, 151 GB at 4-bit. Weights download fine, but
**`mlx-lm` 0.31.3 — the latest release — has no `deepseek_v4` module**, so the model cannot load
(`Model type deepseek_v4 not supported`). Upstream support is an open request, not a merged PR.
MiniMax-M3 was checked as a substitute and is blocked the same way (`minimax_m3_vl`), though its
LICENSE was read and carries **no** geographic restriction.

Options, in the user's hands:
- **a. Wait** for upstream `mlx-lm` support. Keeps the venv clean; the 4-bit weights are already on
  M2 (`~/ai/models/DeepSeek-V4-Flash-4bit`, resume the download when wanted).
- **b. Third-party module.** Community repos publish a `deepseek_v4.py` to drop into
  `mlx_lm/models/`. That is unreviewed code running inside the serving venv — needs explicit
  approval, and should go in an isolated venv, not the one serving Developer/Reviewer.
- **c. Substitute** a supported model for the Developer role. Of the current generation, only
  GLM-5.2 (`glm_moe_dsa`) both runs on `mlx-lm` 0.31.3 and beats Qwen3.6-27B — but at 418 GB it
  cannot share M2 with the Reviewer.

### 3. Local GLM-5.2 on Machine 1 — IN PROGRESS

`mlx-community/GLM-5.2-4bit`, 418 GB, MIT, 1M context, arch confirmed supported by the installed
`mlx-lm`. Download running; serve script (`scripts/start-glm.sh`, port **8005** — 8004 is the MTP
lane) and LaunchAgent (`configs/launchd/com.localai.glm.plist`) are in place.

Two prerequisites before it can load:

1. **GPU wired-memory ceiling** (needs sudo, user action):
   `configs/launchd/com.localai.wiredlimit.plist` sets `iogpu.wired_limit_mb=491520` at boot.
2. **Machine-1 residency**: 418 GB (GLM) + 65 GB (Orchestrator bf16) exceeds 512 GiB. Drop the
   Orchestrator to its 8-bit build (38 GB, already on disk) or stop it while GLM is loaded.

Then repoint meter port `:9004` from `https://api.z.ai/...` to `http://127.0.0.1:8005`, keeping the
cloud upstream on a new port as fallback.

### 4. RAG embedder → Qwen3-Embedding-8B — IN PROGRESS

`mlx-community/Qwen3-Embedding-8B-mxfp8`, 4096-dim, 7.3 GB. Measured on M1: 88 chunks/s,
related pair 0.78 vs unrelated 0.30 cosine. `rag_lib.EMBED_MODEL` now defaults to it.

Because the dimension changes (384 → 4096) every collection is dropped and re-ingested from the
same source files (6,958 of 7,019 still on disk; the 61 missing are moved/deleted files, and the
`server_setup` collection's relative paths re-ingest from the repo root). Qdrant storage backed up
to `~/ai/qdrant-storage.bak-20260809` first.

Defect found during the rebuild: `rag-ingest.py` deletes each file's old chunks with a `path`
filter, and no payload index existed — an unindexed filter is a full scan, which dropped ingest to
~0.7 points/s. Creating the `path` keyword index before ingest restored ~15× throughput.

After ingest, gates must be recalibrated — `min_score` from the old embedder is meaningless for the
new one. The existing `scripts/rag-calibrate.py <collection>` does this: it probes with a relevant
and an off-topic query and writes the midpoint to `rag-collections/<collection>.json`.

## Files changed

- `scripts/start-glm.sh` (new), `configs/launchd/com.localai.glm.plist` (new),
  `configs/launchd/com.localai.wiredlimit.plist` (new)
- `scripts/rag_lib.py` (embedder default)
- `docs/MODELS.md`, `docs/rag.md`
- `local-ai-dashboard`: `src/meter/upstreams.ts`, `src/meter/proxy.ts`, `src/meter/proxy.test.ts`
- `~/ai/local-ai-stack/.env` on M2, `~/ai/dashboard/dashboard.env` (both backed up)

## Acceptance criteria

- Reviewer answers at ≥ 15 tok/s and a stale-model-id request lands on the q8 weights. **Met.**
- Every RAG collection reports `dim=4096` with a point count within ~5% of its old count, and
  `rag-query.py` returns sensible hits above the recalibrated gate.
- GLM-5.2 answers on `127.0.0.1:8005` and `:9004` serves it locally with the cloud kept as fallback.

## Rollback

- Reviewer: set `REVIEW_MODEL_PATH` back to `…-heretic-v2-bf16` (still on disk) and restart; or
  restore `.env.bak-20260809`.
- Meter: unset `METER_REVIEW_MODEL` / `METER_DEV_MODEL` in `dashboard.env` (restore
  `dashboard.env.bak-20260809`); `forceModel` is a no-op when unset.
- RAG: restore `~/ai/qdrant-storage.bak-20260809` over the storage dir and revert
  `rag_lib.EMBED_MODEL` — the two must move together.
- GLM: `launchctl bootout gui/$(id -u)/com.localai.glm`; the wired-limit daemon can be booted out
  and the sysctl reset to 0.

## Risks

- Raising `iogpu.wired_limit_mb` leaves macOS ~32 GiB. Too aggressive a value can hang the machine
  under memory pressure; 480 GiB of 512 GiB is the intended margin.
- The GLM 4-bit conversion omits the MTP block — no speculative-decoding speedup in this build.
- Re-ingest reflects today's files: chunks for the 61 deleted/moved source files are not carried
  over, by design.
- Quantization to 8-bit is not free in principle; the Reviewer's output was spot-checked, not
  benchmarked against a golden set. Run `eval/` if a regression is suspected.
