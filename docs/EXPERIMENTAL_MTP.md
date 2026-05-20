# Experimental MTP-Preserved Model Lane

This repo includes an experimental path for MTP-preserved Qwen3.6-35B-A3B models.

Candidate:

```text
llmfan46/Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved
```

## Why it matters

The model preserves Qwen3.6's native multi-token prediction tensors. In a runtime that supports native MTP, this can potentially speed decoding without a separate draft model.

## Current rule

Do not replace the stable daily Orchestrator or Reviewer until the experimental model wins benchmarks on your actual tasks.

Use it first as:

```text
Security Reviewer
Second-Pass Reviewer
Architecture Reviewer
```

## Endpoint convention

```text
MTP35_BASE_URL=http://10.10.10.2:8004/v1
MTP35_MODEL=mtplx
```

### Why `mtplx` looks like the forbidden `local`/`default` alias — but isn't

The "always use full model paths, never aliases" rule applies to
`mlx_lm.server`, which treats the `model` field as a real path or
Hugging Face repo id and 404s on anything it can't resolve.

`mtplx` here is the name of a *different* serving binary
([github.com/llmfan/mtplx](https://github.com/llmfan/mtplx) and similar
forks experimenting with native MTP heads). When you point this lane at
the `mtplx` runtime, `model=mtplx` is the runtime's own self-referential
identifier — there is no Hugging Face resolution happening. It is safe
in *this exact context* and only this context.

If you serve the experimental weights with stock `mlx_lm.server`
instead, treat them like every other model and use the full path:

```text
MTP35_MODEL=$HOME/ai/models/orchestrator-llmfan46-qwen36-35b-a3b-mtp-preserved-bf16-mlx
```

## Benchmark

Use:

```bash
scripts/bench-chat-endpoint.sh \
  http://10.10.10.2:8004/v1 \
  mtplx \
  benchmarks/prompts/01_architecture_plan.md
```
