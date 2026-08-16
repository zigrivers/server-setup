# Model Manifest

## Stable daily stack

### Orchestrator — Machine 1

```text
TheCluster/Qwen3.6-35B-A3B-Heretic-MLX-bf16
Local path: ~/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16
Endpoint: http://127.0.0.1:8001/v1
```

Optional fallback:

```text
TheCluster/Qwen3.6-35B-A3B-Heretic-MLX-mixed-9bit
Local path: ~/ai/models/orchestrator-qwen36-35b-a3b-heretic-mixed9
```

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

> ### ⚠️ Reviewing is where this model's thinking runs longest — set a token budget
>
> Qwen3.8 scales its reasoning to how open-ended the prompt is, and "list every real bug" is as
> open-ended as it gets. Measured on one identical review prompt (a 13-line function with three
> planted bugs, temperature 0):
>
> | | tokens | wall clock | findings |
> |---|---|---|---|
> | Qwen3.6-27B heretic q8 | 4,970 | 372 s | 3 |
> | Qwen3.8-27B, thinking on | >16,000 | **did not finish in 25 min — killed** | — |
> | Qwen3.8-27B, `enable_thinking: false` | 52 | **4 s** | 2 |
>
> On a *closed* prompt ("name two causes of race conditions") it answers inside 256 tokens in 5 s,
> so this is not general verbosity — it is unbounded deliberation on unbounded questions.
>
> Consequences for callers of `:8003` / `:9003`:
> - A small `max_tokens` does not truncate politely — the budget is spent on reasoning and
>   **`content` comes back empty**. `src/regression/run.ts` sends 256 and `src/shared/llm.ts`
>   defaults to 500; both are below what a hard review needs.
> - Either send `chat_template_kwargs: {"enable_thinking": false}` (fast, slightly shallower — it
>   found 2 of 3 planted bugs instead of 3), or budget 8k+ tokens and expect minutes per review.
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
   418 GB the model needs resident. Install `configs/launchd/com.localai.wiredlimit.plist`.
2. It cannot share Machine 1 with a resident Orchestrator: 418 + 65 GB exceeds 512 GiB. Drop the
   Orchestrator to its 8-bit build (`…-mixed9`, 38 GB) or stop it while GLM is loaded.

Known quant caveat: the mlx-community 4-bit build ships without the MTP block, so GLM-5.2's
speculative-decoding speedup is not available in this conversion.

## Experimental MTP lane

```text
llmfan46/Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved
Role candidates: Orchestrator, Reviewer, Security Reviewer
Endpoint candidate: http://10.10.10.2:8004/v1
```

Use as an experimental endpoint until native MTP support is proven stable in your runtime.
