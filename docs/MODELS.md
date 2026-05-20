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
TheCluster/Qwen3.6-27B-Heretic-MLX-bf16
Local path: ~/ai/models/reviewer-qwen36-27b-heretic-bf16
Endpoint: http://10.10.10.2:8003/v1
```

Alternative Reviewer candidate:

```text
llmfan46/Qwen3.6-27B-uncensored-heretic-v2
Convert to MLX BF16 if desired.
```

## Experimental MTP lane

```text
llmfan46/Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved
Role candidates: Orchestrator, Reviewer, Security Reviewer
Endpoint candidate: http://10.10.10.2:8004/v1
```

Use as an experimental endpoint until native MTP support is proven stable in your runtime.
