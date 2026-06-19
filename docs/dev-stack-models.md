# Dev-stack models — OpenCode + MMR through the meter

How to drive every model (local + GLM-5.2 + DeepSeek) from **OpenCode**, and use them as **MMR**
review channels. Everything routes through the meter, so it all lands in the dashboard
(see [`observability.md`](observability.md)).

## OpenCode

Install the provider config (one time):

```bash
cp configs/opencode/opencode.json.example ~/.config/opencode/opencode.json
opencode models | grep -E 'local-|glm-meter|deepseek-meter'   # confirm providers load
```

Each provider points at a meter port; the `apiKey` is a routing **label** (`"opencode"`), not a
secret. Providers:

| Provider | Meter port | Model id |
|---|---|---|
| `local-orch` | 9001 | the orchestrator model path |
| `local-dev` | 9002 | `llmfan46/Qwen3.6-27B-uncensored-heretic-v2` |
| `local-review` | 9003 | `llmfan46/Qwen3.6-27B-uncensored-heretic-v2` |
| `glm-meter` | 9004 | `glm-5.2` |
| `deepseek-meter` | 9005 | `deepseek-v4-pro`, `deepseek-v4-flash` |

> The `-meter` suffix avoids colliding with OpenCode's built-in `deepseek`/`zai` providers, which
> would otherwise bypass the meter and bill your key directly.

> **Local model ids** are whatever `curl 127.0.0.1:<port>/v1/models` returns on your machines —
> `mlx_lm.server` wants a real path or HF id. Update the example if yours differ.

Use it (interactive `opencode`, or headless):

```bash
opencode run "explain this diff" --model local-dev/llmfan46/Qwen3.6-27B-uncensored-heretic-v2
opencode run "review for races"  --model deepseek-meter/deepseek-v4-pro     # needs DEEPSEEK_API_KEY
opencode run "architecture pass" --model glm-meter/glm-5.2                  # needs ZAI_API_KEY
```

Verified live: a local-dev run flows through the meter and is recorded as `client=opencode,
source=metered`. GLM/DeepSeek are identical once their keys are set (see `observability.md`).

## MMR review channels

MMR channels are CLI commands, so OpenCode is the adapter that lets `mmr review` use GLM-5.2 and
DeepSeek. Merge the example channels into your global MMR config or a project `.mmr.yaml`:

```bash
cat configs/mmr/channels.example.yaml   # opencode-glm + opencode-deepseek
# then, with paid keys set + ports 9004/9005 serving:
mmr review --staged --sync --channels opencode-glm opencode-deepseek
```

This gives a diverse panel: your local reviewer + two frontier families (GLM, DeepSeek) +
claude/codex/gemini — all attributed in the dashboard.

See also: [`observability.md`](observability.md), `plans/2026-06-19-unified-observability-{spec,plan}.md`.
