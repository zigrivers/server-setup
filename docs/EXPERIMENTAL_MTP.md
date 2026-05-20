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

## Benchmark

Use:

```bash
scripts/bench-chat-endpoint.sh \
  http://10.10.10.2:8004/v1 \
  mtplx \
  benchmarks/prompts/01_architecture_plan.md
```
