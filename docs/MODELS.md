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
Jundot/Qwen3.8-27B-oQ8e-mtp            same weights as the developer, via a reviewer-named symlink
Local path: ~/ai/models/reviewer-qwen38-27b-oq8e-mtp -> developer-qwen38-27b-oq8e-mtp
Model id:   reviewer-qwen38-27b-oq8e-mtp
```

Why: the plan was to move the reviewer to a different model family. The candidate,
MiMo-V2.6-Flash (309B / 15B active, 156 GB, MIT), loads and runs on oMLX at 44 tok/s, but on the
code-review eval (19 cases, temperature 0, 2026-10-21) it caught 15/18 planted bugs with thinking
(83%) against the 27B's 17/18 (94%), and 14/18 without. The harness's rule is quality first, so the
27B keeps the slot. What changed is speed: with MTP on oMLX the 27B's thinking review has a median
of 85 s instead of timing out, which is what made the role usable again. MiMo's weights stay on
disk (`~/ai/models/reviewer-mimo-v2.6-flash-mxfp4-q8`) as the fastest second-opinion candidate
(83% at 6 s median) should a speed-first lane be wanted: `OMLX_REVIEW_MODEL` swaps it in.

## Measured gates (2026-10-21)

| Gate | Result |
|---|---|
| Tool-call eval, orchestrator (38 cases) | base oQ4e-mtp on oMLX 97% / 97% (think / no-think); heretic on mlx_lm 100% / 100% |
| Code-review eval, orchestrator | base oQ4e-mtp on oMLX **94%** think, **89%** no-think (p50 0.6 s) |
| Code-review eval, reviewer | Qwen3.8-27B oQ8e-mtp think **94%**; MiMo think 83%, no-think 78% |
| Soak, oMLX orchestrator | 60 min x 8 clients: 1,130 requests, 0 errors, RSS flat; MTP build 30 min: 642 requests, 0 errors |

## Removed from the plan

| Weights | Why |
|---|---|
| `glm-5.2-4bit` (390 GB, M1) | needs an unmerged mlx-lm PR, no MTP, 5.6 tok/s prompt processing at 16K; superseded by GLM-5.3 |
| `DeepSeek-V4-Flash-4bit` (141 GB, M2) | no mlx-lm loader exists |
| `kimi-k26-dq3km-q8` (438 GB, M2) | loads, but scores below Qwen3.8-27B on SWE-bench Pro and fills the whole machine |
| `*-mtp-drafter` files | mlx-lm's `--draft-model` cannot load them (issue #1462); oMLX uses the heads inside the `*-mtp` builds instead |

Deleted 2026-10-21 (~1 TB freed; the GLM-5.2 copy on M1 sits in the Trash until emptied). `scripts/check-mlx-blockers.sh` still watches the upstream PRs, so a merge would mean re-downloading, not flipping a switch.

## Embeddings (unchanged)

`~/ai/models/qwen3-embedding-0.6b-8bit`, `~/ai/models/qwen3-embedding-8b-mxfp8` for the RAG proxy.
