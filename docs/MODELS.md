# Model Manifest

Served by oMLX (see `docs/OMLX.md`). Decided by measurement on 2026-10-21; the research behind the
choices is in `~/Developer/reports/Local model upgrade options Oct 2026.md`.

## Stable daily stack

### Orchestrator — Machine 1 (`http://127.0.0.1:8001/v1`, meter `:9001`)

```text
Jundot/Qwen3.6-35B-A3B-oQ4e-mtp        base Qwen3.6-35B-A3B (35B total / 3B active), ~4.7 bits/weight, MTP head kept, 20 GB
Local path: ~/ai/models/orchestrator-qwen36-35b-a3b-oq4e-mtp
Model id:   orchestrator-qwen36-35b-a3b-oq4e-mtp
```

Why: nothing in the 3B-active tier beats Qwen3.6-35B-A3B for planning/routing, and the base weights
replace the abliterated "heretic" build, whose tool-calling fidelity nobody had measured. Measured
90 tok/s decode on oMLX (19 tok/s before).

Rollback weights (still on disk): `~/ai/models/orchestrator-qwen36-35b-a3b-heretic-mixed9`.

### Developer — Machine 2 (`http://10.10.10.2:8002/v1`, meter `:9002`)

```text
Jundot/Qwen3.8-27B-oQ8e-mtp            Qwen3.8-27B dense, 8-bit, MTP head kept, 28 GB
Local path: ~/ai/models/developer-qwen38-27b-oq8e-mtp
Model id:   developer-qwen38-27b-oq8e-mtp
```

Why: Qwen3.8-27B scores 86.0% on the independent Vals.ai SWE-bench Verified leaderboard (above
Alibaba's own 2.4T flagship); no mid-size open model has evidence of beating it. MTP lifts it from
20 to 47 tok/s with identical output at temperature 0.

### Reviewer — Machine 2 (`http://10.10.10.2:8003/v1`, meter `:9003`)

```text
mlx-community/MiMo-V2.6-Flash-RL-mxfp4-q8   309B total / 15B active MoE, MIT, 156 GB on disk (~170 GB loaded)
Local path: ~/ai/models/reviewer-mimo-v2.6-flash-mxfp4-q8
Model id:   reviewer-mimo-v2.6-flash-mxfp4-q8
```

Why: the reviewer was the same 27B weights as the developer loaded twice, so it shared the author's
blind spots and, at 20 tok/s, timed out on real reviews (the `local_review` tool had been rerouted
to the orchestrator because of it). MiMo is a different model family, 2.5x faster to decode, and
vendor-reported well ahead on agentic coding (Terminal-Bench 2.1 87.6 vs 73.0). Independent scores
do not exist yet, so it is gated by the code-review eval in the dashboard repo
(`eval/results/2026-10-21-*`). Override with `OMLX_REVIEW_MODEL=~/ai/models/developer-qwen38-27b-oq8e-mtp`
to fall back to the 27B.

## Removed from the plan

| Weights | Why |
|---|---|
| `glm-5.2-4bit` (390 GB, M1) | needs an unmerged mlx-lm PR, no MTP, 5.6 tok/s prompt processing at 16K; superseded by GLM-5.3 |
| `DeepSeek-V4-Flash-4bit` (141 GB, M2) | no mlx-lm loader exists |
| `kimi-k26-dq3km-q8` (438 GB, M2) | loads, but scores below Qwen3.8-27B on SWE-bench Pro and fills the whole machine |
| `*-mtp-drafter` files | mlx-lm's `--draft-model` cannot load them (issue #1462); oMLX uses the heads inside the `*-mtp` builds instead |

They are still on disk until the operator deletes them (~1 TB).

## Embeddings (unchanged)

`~/ai/models/qwen3-embedding-0.6b-8bit`, `~/ai/models/qwen3-embedding-8b-mxfp8` for the RAG proxy.
