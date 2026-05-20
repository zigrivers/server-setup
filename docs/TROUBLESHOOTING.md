# Troubleshooting

## Hugging Face 404 for `local` or `default`

Cause: request used `"model": "local"` or `"model": "default"` against `mlx_lm.server`.

Fix: use the full model path as seen by the server machine.

```text
ORCH_MODEL=/Users/admin/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16
DEV_MODEL=/Users/admin/ai/models/developer-qwen36-27b-heretic2-mixed94
REVIEW_MODEL=/Users/admin/ai/models/reviewer-qwen36-27b-heretic-bf16
```

## `zsh: no matches found: huggingface_hub[hf_xet]`

Quote extras in zsh:

```bash
uv pip install 'huggingface_hub[hf_xet]'
```

## `mlx_lm.generate: command not found`

Activate the venv where `mlx-lm` is installed:

```bash
cd ~/ai/local-ai-stack
source .venv/bin/activate
which mlx_lm.generate
```

Install if missing:

```bash
uv pip install mlx-lm
```

## Thunderbolt IP not reachable

From Machine 1:

```bash
ping 10.10.10.2
```

Check macOS Network settings on both machines:

```text
Thunderbolt Bridge
Machine 1 IP: 10.10.10.1
Machine 2 IP: 10.10.10.2
Subnet: 255.255.255.0
Router: blank
```

## SSH connection closed

On Machine 2:

```bash
whoami
sudo systemsetup -getremotelogin
sudo systemsetup -setremotelogin on
sudo lsof -nP -iTCP:22 -sTCP:LISTEN
```

Use the exact short username:

```bash
ssh admin@10.10.10.2
```

## Endpoint down

Check listening ports:

```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN
lsof -nP -iTCP:8002 -sTCP:LISTEN
lsof -nP -iTCP:8003 -sTCP:LISTEN
```

Check logs:

```bash
tail -100 ~/ai/logs/orchestrator.log
tail -100 ~/ai/logs/developer.log
tail -100 ~/ai/logs/reviewer.log
```

## Machine feels sluggish

Check memory pressure:

```bash
memory_pressure
```

If Machine 1 is sluggish, switch the Orchestrator from BF16 to mixed-9bit.
