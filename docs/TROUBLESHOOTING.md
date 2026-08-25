# Troubleshooting

## Hugging Face 404 for `local` or `default`

Cause: request used `"model": "local"` or `"model": "default"` against `mlx_lm.server`.

Fix: use the full model path as seen by the server machine.

```text
ORCH_MODEL=$HOME/ai/models/orchestrator-qwen36-35b-a3b-heretic-bf16
DEV_MODEL=$HOME/ai/models/developer-qwen36-27b-heretic2-mixed94
REVIEW_MODEL=$HOME/ai/models/reviewer-qwen36-27b-heretic-bf16
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

### Is the machine down, or only the link?

These look identical from Machine 1 — both make `10.10.10.2` unreachable — but the
fixes are opposite. Ask the second path first:

```bash
nc -z -G 3 100.71.251.23 22 && echo "M2 is UP — the private link is the problem"
```

`100.71.251.23` is M2 on Tailscale (node `ai-inference`). If it answers, the machine
is awake and Wake-on-LAN cannot help you; go look at the cable. `scripts/m2-watchdog.sh`
now makes this call automatically and logs `M2 itself is ALIVE via ...` when it applies
(override the address with `M2_ALT_HOST`, or set it empty to disable the check).

Then confirm the bridge on **both** machines:

```bash
ifconfig bridge0 | grep -E "status|inet "
```

`status: inactive` with no `inet` line means the Thunderbolt ports see no peer — reseat
the cable. The static addresses are stored per-machine and reapply on their own once the
bridge comes up; you do not need to reconfigure anything:

```bash
networksetup -getinfo "Thunderbolt Bridge"   # expect Manual, 10.10.10.1 (M1) / 10.10.10.2 (M2)
```

**The workers do not need restarting after a link drop.** `mlx_lm.server` binds to
`10.10.10.2` at startup and keeps that socket when the address disappears, so the
processes stay alive and look healthy in `ps` while accepting nothing. Reconnecting the
cable makes them reachable again instantly, with the models still warm in memory. Killing
them costs a multi-minute reload and fixes nothing (observed 2026-08-17).

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

## Requests hang for minutes while the endpoint still looks healthy

Symptom: the dashboard shows the endpoint green and `/v1/models` answers instantly, but
every chat request hangs until the client's own timeout. Clients report
`UND_ERR_BODY_TIMEOUT` or `UND_ERR_HEADERS_TIMEOUT`, never an HTTP error.

**Every mlx endpoint is affected**, not just the orchestrator. Look for a dead generation thread in
the relevant server log:

```bash
grep -n "Resource limit\|Exception in thread Thread-1" ~/ai/logs/orchestrator.log | tail   # M1
ssh m2 'grep -c "Resource limit" ~/ai/logs/developer.log ~/ai/logs/reviewer.log'            # M2
```

```
RuntimeError: [metal::malloc] Resource limit (499000) exceeded.
```

**This is not an out-of-memory error.** 499000 is a cap on the *number* of live Metal
buffers a process may hold, not their size — a probe allocating 499,000 tiny arrays throws
at exactly that count with 2 MB in use. The cap is per process, so a second model server on
the same Mac does not eat into it.

The cause is a leak of live Metal buffer descriptors in mlx-lm's decode path, tracked
upstream in [mlx-lm#831](https://github.com/ml-explore/mlx-lm/issues/831),
[#1185](https://github.com/ml-explore/mlx-lm/issues/1185) and
[#1332](https://github.com/ml-explore/mlx-lm/issues/1332). All three are open; there is no
released fix. It kills the server's single generation thread while the HTTP thread keeps
serving `/v1/models`, which is why nothing short of a real completion detects it.

Restarting the server is the only remedy. On M1:

```bash
launchctl kickstart -k "gui/$(id -u)/com.localai.orchestrator"
```

On M2 the workers are LaunchDaemons with `KeepAlive SuccessfulExit=false`, so killing the
process is enough — launchd loads a fresh one, and **no sudo is needed** because the daemon
runs as `admin`:

```bash
ssh m2 "pkill -f 'mlx_lm[.]server.*--port 8002'"   # developer;  8003 = reviewer
```

(The `[.]` keeps the pattern from matching the shell that is running `pkill`.)

`scripts/m2-watchdog.sh` now handles all three automatically, by two different routes:

- **Orchestrator (M1):** greps its server log every tick and restarts on first sight of the
  traceback, instead of waiting out two failed completion probes (~9 minutes).
- **Developer and reviewer (M2):** judged from the meter's telemetry, since reading M2's logs
  would mean an ssh on every tick. An upstream carrying 3+ chat failures and *zero* successes
  over 15 minutes is wedged by definition; only the restart crosses the link. Failures
  alongside successes are ordinary life on a busy server and are left alone.

Observed 2026-08-24: four orchestrator crashes in 90 minutes under a long OpenCode session,
16 failed requests. Observed 2026-08-24/25: developer and reviewer both crashed overnight and
served nothing for seven hours, 126 failed requests, because nothing was watching them.

**Reduce how often it fires** by keeping very long contexts off the orchestrator. Measured
over that day's traffic, the orchestrator is much faster than the developer endpoint below
150k tokens and much slower above it — which is also where it crashes:

| Prompt size | Orchestrator | Developer |
| --- | --- | --- |
| 50–100k | 6.0s | 100.4s |
| 100–150k | 23.9s | 83.0s |
| >150k | 173.9s | 67.9s |

## Machine feels sluggish

Check memory pressure:

```bash
memory_pressure
```

If Machine 1 is sluggish, switch the Orchestrator from BF16 to mixed-9bit.

## Orchestrator answers ~50% instant 403/404 (port hijack by Docker)

**Symptom (2026-08-12, real incident):** the dashboard showed a ~50% orchestrator
error rate — tens of thousands of `HTTP 403` rows, all 1-3 ms latency — while the
orchestrator's own log showed nothing but 200s. Direct `curl` to
`127.0.0.1:8001` intermittently got 403/404/dropped connections.

**Cause:** a Docker container (OrbStack) published `0.0.0.0:8001->8001`
(`nibble-research-engine-1`, itself unhealthy). mlx_lm.server binds
`127.0.0.1:8001` specifically; with a second wildcard listener on the same
port, macOS distributes incoming loopback connections between BOTH listeners —
roughly half of all requests landed on the container, which instantly rejected
them. The failures never appear in the orchestrator's log because those
requests never reached it.

**Diagnose:**

```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN     # more than one listener = the bug
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 8001
```

**Fix:** stop the container (`docker stop <name>`) or remap its host port in
its compose file (e.g. `127.0.0.1:18001:8001`, or a high port like the nibble
worktree variants already use). The AI-stack ports to keep clear of published
container ports: 8001-8006, 9001-9008, 9100, 9200, 3111.
