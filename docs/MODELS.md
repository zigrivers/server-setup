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
TheCluster/Qwen3.6-27B-Heretic2-Uncensored-Finetune-Thinking-MLX-mixed-9.4bit
Local path: ~/ai/models/developer-qwen36-27b-heretic2-mixed94
Endpoint: http://10.10.10.2:8002/v1
```

### Reviewer — Machine 2

```text
llmfan46/Qwen3.6-27B-uncensored-heretic-v2, quantized locally to 8-bit (affine, group 32)
Local path: ~/ai/models/reviewer-llmfan46-qwen36-27b-heretic-v2-q8
Endpoint: http://10.10.10.2:8003/v1
```

Was BF16 (`…-heretic-v2-bf16`, 50 GB, ~6 tok/s) until 2026-08-09. The 8-bit rebuild is 28 GB and
measured ~19.5 tok/s on the same prompt — same weights, same recipe the Developer already used.
Rebuild command:

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
