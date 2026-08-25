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

### Why local turns used to stop mid-task

The symptom was OpenCode going quiet part-way through a job, needing a typed "continue". Measured
2026-08-25 from OpenCode's own session database (58k assistant turns), its log, and the meter.

**It was almost always the endpoint dying, not OpenCode losing its place.** Turns that never
completed, over 7 days: glm-meter 0.9%, local-orch 0.0%, local-dev 38.1%. Broken down by hour,
2026-08-25 00:00–04:00 shows 40 local turns and 40 failures — exactly the M2 wedge window. Earlier,
5,167 of 5,430 `local-review` stream errors were `Bad Gateway` clustered on Aug 2–6, the M2 outage
that went unreported for four days.

What made it *look* like an OpenCode fault is that it fails silently: three retries, an
`AI_RetryError: Failed after 3 attempts` line in its log, then the turn simply ends with nothing on
screen. `configs/opencode/plugins/local-stall-alert.mjs` now raises a desktop notification on
`session.error` so an outage announces itself.

The second cause was real but rarer: the orchestrator hit its output ceiling and was cut off
mid-work. Only 2 of 34 recorded "continue" nudges followed a local turn, and both had
`finish=length`. `local-orch` truncates on 1.2% of turns against glm-5.2's 0.01%.

Two upstream OpenCode bugs make both worse and **cannot be fixed from here**: SSE/chunk timeouts are
not classified as retryable, so such a turn dies with no retry
([#20466](https://github.com/anomalyco/opencode/issues/20466)); and a successful response carrying
zero content reads as "task complete" ([#31430](https://github.com/anomalyco/opencode/issues/31430)).
The second does not currently affect this stack — zero of 4,315 captured local responses were empty.

### What each local setting is for

| Setting | Value | Why |
|---|---|---|
| `limit.context` | 131,072 | Below the measured crossover where the orchestrator stops being the faster endpoint |
| `limit.output` | 32,000 | The ceiling the orchestrator has actually hit; OpenCode clamps the wire value at 32,000 regardless of a higher number here |
| `options.timeout` | 1,800,000 | 32,000 tokens at ~12 tok/s is ~45 min worst case; 30 min covers real work while still bounding a hang |
| `options.chunkTimeout` | 300,000 | Gap *between* chunks. Worst observed time-to-first-token on these endpoints is 209s |
| `compaction.reserved` | 16,000 | A thinking model needs room to write the summary |
| `tools` | 1 disabled | `local-ai-delegate_run_local_plan` was never called once in 47,240 recorded tool calls, yet shipped in every request |
| `small_model` | local-orch | 21,734 title generations were going to a paid cloud model |

Not set: `steps`. Leaving it unset lets an agent iterate until the model stops, which is what you
want for long local jobs — capping it forces a text-only summary mid-task, which looks exactly like
the stall this section is about.

### Keep the system prompt small

Every local turn pays for the whole request up front. Measured with a throwaway recording endpoint,
the request for the message "say hi" was 121 KB — an 81,046-character system prompt plus 19 tool
definitions, about 29k tokens, roughly 20 seconds of prompt processing before the first token.

15% of that system prompt was the same text twice. `~/.config/opencode/AGENTS.md` is a symlink to
`new-mac/config/agents/AGENTS.md`, OpenCode auto-loads it, and `instructions` named the same file
again by its real path — so every house rule was sent twice. Removing the `instructions` entry cut
12,555 characters per request with nothing lost.

If you add MCP servers, check what they cost here before keeping them: tool definitions alone were
31 KB of that request.

Four tools were never called once in 47,240 recorded tool calls. Only one of them can be turned
off. `local-ai-delegate_run_local_plan` takes the documented `tools` entry because it carries its
MCP server's prefix. The other three — `list_mcp_resources`, `list_mcp_resource_templates` and
`read_mcp_resource` — are OpenCode built-ins that appear whenever any MCP server is configured, and
**they cannot be disabled from config**: `mcp*`, `*resource*` and `*mcp_resource*` were each tested
against a recording endpoint and left all three in the tool list. The only way to drop them is to
remove every MCP server, which costs more than it saves.

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
