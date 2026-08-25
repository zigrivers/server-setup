# Model Manifest

## Stable daily stack

### Orchestrator — Machine 1

```text
TheCluster/Qwen3.6-35B-A3B-Heretic-MLX-mixed-9bit   (qwen3_5_moe, 40 layers, 256 experts, 38 GB)
Local path: ~/ai/models/orchestrator-qwen36-35b-a3b-heretic-mixed9
Endpoint: http://127.0.0.1:8001/v1   (metered on :9001)
```

This is what `com.localai.orchestrator` actually loads — the plist sets `ORCH_MODEL_PATH` to the
mixed-9bit build, which is also what `METER_ORCH_MODEL` pins on `:9001`. The bf16 build below is
still on disk as a fallback but is **not** served.

```text
TheCluster/Qwen3.6-35B-A3B-Heretic-MLX-bf16   (65 GB, fallback only)
Local path: ~/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16
```

> **Known failure, affecting EVERY mlx endpoint here — not only this one.** mlx-lm leaks live Metal
> buffer descriptors while decoding and eventually throws
> `[metal::malloc] Resource limit (499000) exceeded` — a cap on the *number* of live Metal buffers,
> not on memory, so the machine is not out of RAM when it fires. It kills the server's generation
> thread while the process keeps answering `/v1/models` with 200, so only a real completion detects
> it. Upstream: [mlx-lm#831](https://github.com/ml-explore/mlx-lm/issues/831),
> [#1185](https://github.com/ml-explore/mlx-lm/issues/1185),
> [#1332](https://github.com/ml-explore/mlx-lm/issues/1332) — all open, no released fix, so
> restarting is the only lever.
>
> Seen on the orchestrator (2026-08-24, four crashes in 90 minutes) and on both M2 workers
> (2026-08-24/25, seven hours serving nothing). `scripts/m2-watchdog.sh` now covers all three; see
> `docs/TROUBLESHOOTING.md` for how it detects each and for the measured context crossover that
> makes it fire less often.

### Developer — Machine 2

```text
mlx-community/Qwen3.8-27B-8bit   (qwen3_5 arch, 8-bit affine g64, 28 GB, 262k ctx, Apache-2.0)
Local path: ~/ai/models/developer-qwen38-27b-8bit
Endpoint: http://10.10.10.2:8002/v1
```

Upgraded from `developer-qwen36-27b-heretic2-mixed94` on 2026-08-16. Qwen3.8 reports the same
`model_type: qwen3_5` as Qwen3.6, so it loads on the installed mlx-lm 0.31.3 unchanged — unlike
GLM-5.2 and DeepSeek-V4, this generation needed no new model code.

Measured on an identical prompt (merge-intervals with tests, temperature 0, 6k budget):

| | Qwen3.6-27B (heretic2, 8-bit) | Qwen3.8-27B (stock, 8-bit) |
|---|---|---|
| completion tokens | 1,926 | **1,153** |
| wall clock | 97.3 s | **57.5 s** |
| tok/s | 19.8 | 20.1 |
| reasoning chars / answer chars | 5,448 / 583 | **3,306** / 640 |
| generated tests | pass | pass |
| resident memory | 30 GB | **27 GB** |

Same speed per token; it simply thinks less to reach a correct answer. Vendor-reported benchmarks
put it well ahead on coding too (SWE-bench Pro 61.7 vs 53.5, LiveCodeBench v6 90.3 vs 83.9).

**This one is NOT abliterated** — the previous Developer was a `heretic` finetune, this is stock
Qwen. The only abliterated MLX build on the Hub (`PocketAiHub/Qwen3.8-27B-Abliterated-MLX`) has no
downloads and declares no quantization, so it was not used. If refusals get in the way, convert a
reputable abliterated BF16 build (huihui-ai, Blackfrost-AI) with the same `mlx_lm.convert` recipe
used for the Reviewer. Rollback is one line: `DEV_MODEL_PATH` in M2's `.env` (backup:
`.env.bak-20260816`); the Qwen3.6 weights stay on disk.

There is no Qwen3.8 counterpart for the Orchestrator — the release shipped only this 27B dense and
a 2.4T-A95B (`qwen3_5_moe_text`, ~1.2 TB at 4-bit, unsupported by mlx-lm 0.31.3).

### Reviewer — Machine 2

```text
mlx-community/Qwen3.8-27B-8bit   (same weights the Developer serves — one copy on disk)
Local path: ~/ai/models/developer-qwen38-27b-8bit
Endpoint: http://10.10.10.2:8003/v1
```

Upgraded from `reviewer-llmfan46-qwen36-27b-heretic-v2-q8` on 2026-08-16. Both 27B endpoints now
serve the same file; each `mlx_lm.server` keeps its own copy resident (~27 GB each), so the cost is
memory, not disk.

> ### Measured against Qwen3.6 — 18 planted bugs, 4 clean cases, temperature 0
>
> Run with `local-ai-dashboard`'s model-comparison harness
> (`src/modeleval/`, results in `eval/results/2026-08-16b-qwen38-vs-qwen36/`):
>
> | arm | recall | false alarms | truncated | p50 latency |
> |---|---|---|---|---|
> | Qwen3.6-27B heretic q8 | 83% (15/18) | 0/4 | 0 | 92.6 s |
> | **Qwen3.8-27B, thinking on** | **89% (16/18)** | 0/4 | 1 | **46.7 s** |
> | Qwen3.8-27B, `enable_thinking: false` | 72% (13/18) | 1/4 | 0 | 3.2 s |
>
> Blind position-swapped judge: Qwen3.8-thinking beat Qwen3.6 on 8 cases, lost 4, tied 6.
> McNemar on discordant bug-level outcomes gives p = 1.000 — with only 18 planted bugs the recall
> gap is **not statistically significant**. The honest reading is "no evidence of harm, several
> signals in favour", not "proven better".
>
> **Do not disable thinking to make reviews fast.** It costs 17 points of recall (89% → 72%) and
> produced the run's only false alarm. An earlier recommendation in this repo to run review
> harnesses with `enable_thinking: false` was wrong, and this eval is what corrected it.
>
> Consequences for callers of `:8003` / `:9003`:
> - Budget **12k+ tokens** for open-ended review. At 8k, one case in nineteen still truncated
>   mid-reasoning (400 s, 8,000 tokens, no verdict). `src/regression/run.ts` sends 256 and
>   `src/shared/llm.ts` defaults to 500 — far below what a hard review needs.
> - Expect a long tail: p50 is 47 s but p90 is 314 s and the max was 401 s.
> - The meter caps `:9003` at 2 in-flight (`METER_REVIEWER_MAX_INFLIGHT`), so multi-minute reviews
>   queue behind each other. `:9006` spills to the Orchestrator instead of queueing.
>
> Rollback is one line — `REVIEW_MODEL_PATH` in M2's `.env` (backup `.env.bak-20260816b`); the
> Qwen3.6 q8 weights are still on disk at `~/ai/models/reviewer-llmfan46-qwen36-27b-heretic-v2-q8`.

The previous Reviewer was BF16 (`…-heretic-v2-bf16`, 50 GB, ~6 tok/s) until 2026-08-09, then the
local 8-bit rebuild (28 GB, ~19.5 tok/s). Rebuild command, still the recipe to use for converting
any abliterated BF16 build to MLX:

```text
mlx_lm.convert --hf-path ~/ai/models/reviewer-llmfan46-qwen36-27b-heretic-v2-bf16 \
  --mlx-path ~/ai/models/reviewer-llmfan46-qwen36-27b-heretic-v2-q8 \
  -q --q-bits 8 --q-group-size 32 --q-mode affine
```

The BF16 copies stay on disk (`…-heretic-v2-bf16`, and the 51 GB HF cache entry) as rollback.

> **Model ids are load instructions.** `mlx_lm.server` LOADS whatever id a client sends, so a client
> still asking for `llmfan46/Qwen3.6-27B-uncensored-heretic-v2` would pull the old BF16 out of the HF
> cache and quietly get the slow model. The meter now pins each local endpoint to its served weights
> via `METER_REVIEW_MODEL` / `METER_DEV_MODEL` in `~/ai/dashboard/dashboard.env`.

### VLM judge — Machine 2

```text
mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit   (17 GB, HF cache)
Served by: mlx_vlm server (own venv: ~/ai/venvs/vlm, mlx-vlm 0.6.12)
Endpoint: http://10.10.10.2:8006/v1
Metered lane (Machine 1): http://127.0.0.1:9008/v1
Launcher: scripts/start-vlm-judge.sh + configs/launchd/com.localai.vlm-judge.plist
```

Serves the **2d-3d-pipeline's** concept/mesh judge (`vlm_judge.py`, items 17-18
of that repo's 2026-08 refresh) so judge calls need no in-process model load and
no vlm-env on the calling machine. The pipeline opts in via
`PIPELINE_JUDGE_ENDPOINT=http://127.0.0.1:9008/v1` (generic OpenAI-compatible
endpoint flag on the pipeline side; nothing there assumes this stack). Scores
verified identical to the in-process path on real fixtures (2026-08-12).

Measured on 2026-08-12 with developer+reviewer serving live traffic on the same
Studio: ~18-19 s per fresh judge call (decode 4-6 tok/s under contention),
~2.6 s on a repeat image (server-side vision cache). The meter caps the lane at
`METER_VLM_MAX_INFLIGHT` (default 2) so judge fan-out never starves the
developer/reviewer lanes.

### Embedding model (RAG) — Machine 1

```text
mlx-community/Qwen3-Embedding-0.6B-8bit   (1024-dim, 619 MB)
Local path: ~/ai/models/qwen3-embedding-0.6b-8bit
Used by: scripts/rag_lib.py (RAG_EMBED_MODEL), rag-proxy on 127.0.0.1:9200
```

The 8B sibling (`~/ai/models/qwen3-embedding-8b-mxfp8`, 4096-dim, 7.3 GB) is on disk and was
benchmarked head-to-head on real 800-char chunks: same separation (related 0.78 / unrelated 0.30
vs 0.75 / 0.32) but **5 chunks/s against 200**, and ~300 ms of added query latency instead of 22 ms.
Retrieval quality did not pay for it at this corpus size.

Replaced `mlx-community/bge-small-en-v1.5-bf16` (384-dim, 2023) on 2026-08-09. Changing it requires
re-ingesting every collection and re-running `scripts/rag-calibrate.py --write`; see `docs/rag.md`.

## Local GLM — Machine 1 (BLOCKED on mlx-lm, 2026-08-09)

> **Does not load on mlx-lm 0.31.3.** GLM-5.2's IndexShare reuses one attention indexer across
> every four layers, so the checkpoint carries indexer weights on 21 of 78 layers; stock mlx-lm
> builds one per layer and fails with `Missing 285 parameters`. Support is
> [mlx-lm PR #1410](https://github.com/ml-explore/mlx-lm/pull/1410) — **open, not merged**.
> Decision 2026-08-09: stay on the z.ai cloud endpoint and revisit when the PR lands. The weights
> and launcher below stay in place for that day.
>
> `mlx-community/GLM-5-4bit` (the June predecessor) *does* carry an indexer on every layer and
> would load on stock mlx-lm, if a local GLM becomes urgent before the PR merges.


```text
mlx-community/GLM-5.2-4bit   (glm_moe_dsa, 743B total / 40B active, MIT, 1M ctx, 418 GB on disk)
Local path: ~/ai/models/glm-5.2-4bit
Endpoint: http://127.0.0.1:8005/v1   (8004 is the MTP lane)
Launcher: scripts/start-glm.sh + configs/launchd/com.localai.glm.plist
```

Replaces the paid z.ai endpoint the meter fronts on `:9004`. Two prerequisites:

1. `iogpu.wired_limit_mb` must be raised — the macOS default (~75% of RAM, ~384 GB) is below the
   418 GB the model needs resident. **Done on both machines** (M1 2026-08-09, M2 2026-08-24):
   `sysctl iogpu.wired_limit_mb` reports `491520` on each, applied at boot by
   `com.localai.wiredlimit` in `/Library/LaunchDaemons/`. Nothing to redo.
2. It cannot share Machine 1 with a resident Orchestrator: 418 + 65 GB exceeds 512 GiB. Drop the
   Orchestrator to its 8-bit build (`…-mixed9`, 38 GB) or stop it while GLM is loaded.

Known quant caveat: the mlx-community 4-bit build ships without the MTP block, so GLM-5.2's
speculative-decoding speedup is not available in this conversion.

## Bulk-classification lane (on demand)

```text
scripts/start-enrich-lane.sh   ->  http://127.0.0.1:8010/v1
Orchestrator weights on mlx-vlm (no thinking template) + MTP drafter, isolated venv ~/ai/mtp-venv
```

A speed option for six-figure batch jobs, started by hand and stopped after. Measured 2026-08-24 on
the Phase 8 enrichment prompt: `:9001` with `enable_thinking=False` does 1.17s/item with valid JSON
every time; this lane does 0.72s (~1.6x, ~2,600 items/hour). Use `:9001` for anything smaller — it
is already running and already metered.

**Never point review or coding traffic at it.** mlx-vlm cannot enable thinking, and the code-review
eval measured that at 89% -> 78% recall.

Stop it when the batch finishes — it pins ~40 GB whether or not anything is calling it:

```bash
pkill -f 'mlx_vlm server.*--port 8010'
```

(Left running idle from 10:16 to 18:20 on 2026-08-24 after the Phase 8 batch; stopped by hand.)

## Kimi K2.6 — on disk, runnable, not yet served (as of 2026-08-24)

```text
kimi-k26-dq3km-q8   (kimi_k25, 1.04T MoE, 4-bit, 256k ctx, modified MIT, 438 GB)
Local path (M2): ~/ai/models/kimi-k26-dq3km-q8
```

Unlike GLM-5.2 and DeepSeek-V4, **nothing upstream blocks this one** — `kimi_k25` is implemented in
the installed mlx-lm 0.31.3, and M2's memory ceiling is now raised. It is the strongest open-weight
writer available here (the Kimi line ranks second on EQ-Bench Creative Writing, behind only Claude
Opus 5), which is why it is the candidate for the `primary-intel-history` writing work rather than
for coding.

The one open question is layout, deferred 2026-08-24: at ~454 GB resident it cannot share M2 with
the Developer and Reviewer (55 GB). Serving it means either moving those two to M1 — clients are
unaffected, since they address meter ports and only the meter's target changes — or stopping them
while Kimi is loaded.

## Experimental MTP lane

```text
llmfan46/Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved
Role candidates: Orchestrator, Reviewer, Security Reviewer
Endpoint candidate: http://10.10.10.2:8004/v1
```

Use as an experimental endpoint until native MTP support is proven stable in your runtime.
