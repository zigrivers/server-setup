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

| Provider | Meter port | Model id | Context cap |
|---|---|---|---|
| `local-orch` | 9001 | `/Users/kenallred/ai/models/orchestrator-qwen36-35b-a3b-heretic-mixed9` | 131,072 |
| `local-dev` | 9002 | `/Users/admin/ai/models/developer-qwen38-27b-8bit` | 131,072 |
| `local-review` | 9006 | `/Users/admin/ai/models/developer-qwen38-27b-8bit` | 131,072 |
| `glm-meter` | 9004 | `glm-5.2`, `glm-5.3` | 1,000,000 |
| `deepseek-meter` | 9005 | `deepseek-v4-pro`, `deepseek-v4-flash` | provider default |

> The `-meter` suffix avoids colliding with OpenCode's built-in `deepseek`/`zai` providers, which
> would otherwise bypass the meter and bill your key directly.

> **Local model ids** are whatever `curl 127.0.0.1:<port>/v1/models` returns on your machines —
> `mlx_lm.server` wants a real path or HF id, and treats it as an instruction to **load** that
> model, not to select one. A stale id here is how the stack ends up serving two copies. The meter
> pins the right model per port (`METER_ORCH_MODEL`, `METER_DEV_MODEL`, `METER_REVIEW_MODEL`), which
> masks a wrong id rather than fixing it — keep these accurate anyway.

### Why the local models carry a context cap

The mlx servers leak Metal buffer descriptors while decoding and eventually die with
`[metal::malloc] Resource limit (499000) exceeded` (see [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)).
Longer prompts mean more work per turn and reach that ceiling sooner: on 2026-08-24/25 OpenCode
sessions that grew past 170k tokens crashed the orchestrator four times in 90 minutes, and both M2
workers overnight.

`limit.context` is what OpenCode compacts against, so capping it makes sessions summarise instead of
growing without bound. 131,072 was chosen because the orchestrator is dramatically faster than the
developer endpoint below ~150k tokens and slower above it, so the cap sits below that crossover and
costs nothing in practice:

| Prompt size | Orchestrator | Developer |
|---|---|---|
| 50–100k | 6.0s | 100.4s |
| 100–150k | 23.9s | 83.0s |
| >150k | 173.9s | 67.9s |

The matching `compaction` block turns on auto-compaction and tool-output pruning, and reserves
16,000 tokens — enough headroom for a thinking model to produce the summary.

**This reduces how often the crash fires; it does not fix it.** The leak is upstream and unfixed,
which is why `scripts/m2-watchdog.sh` still watches all three endpoints.

Use it (interactive `opencode`, or headless):

```bash
opencode run "explain this diff" --model local-dev//Users/admin/ai/models/developer-qwen38-27b-8bit
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
