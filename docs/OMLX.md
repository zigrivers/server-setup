# oMLX runtime

Since 2026-10-21 every role is served by [oMLX](https://github.com/jundot/omlx) (Apache 2.0) instead
of `mlx_lm.server`. `mlx_lm.server` stays installed as the rollback path.

## Why

Measured on 2026-10-21, same machine (M1, M3 Ultra 512 GB), same Qwen3.6-35B-A3B weights, thinking
off, 400-token answer:

| Path | Decode | Prompt processing (34K-token diff) |
|---|---|---|
| `mlx_lm.server` behind the #1845 leak shim (what ran in production) | 19 tok/s | 1,090 tok/s |
| stock `mlx_lm.server` 0.31.3 | 44 tok/s | — |
| `mlx_lm.generate`, no server | 62 tok/s | — |
| oMLX 0.7.2 | 90 tok/s | 2,180 tok/s, 0.5 s on a repeat (prompt cache) |

The shim exists because upstream mlx-lm issue #1845 (a Metal buffer leak on the hybrid
Gated-DeltaNet models) is still open; oMLX ships its own engine patches for those models and did
not leak in a one-hour, eight-client soak (RSS flat, zero errors).

oMLX also runs the models' native multi-token-prediction (MTP) heads, a built-in form of
speculative decoding: the model guesses a few tokens ahead and verifies them in one pass, so the
answer is identical at temperature 0 but arrives faster. The `*-mtp` builds keep those heads.
Measured on M2: Qwen3.8-27B 8-bit went from 20 tok/s (MTP off) to 47 tok/s (MTP on, 71% of
drafted tokens accepted).

## Layout

| | |
|---|---|
| Install | `~/ai/omlx/.venv` on each Mac (Python 3.12 via `uv`, wheel from the GitHub release). Separate from the stack's `.venv`, which still holds mlx-lm 0.31.3 for rollback. |
| Launcher | `scripts/omlx-serve.sh`, called by `scripts/start-<role>.sh` with `ROLE`, `PORT`, `HOST`, `MODEL`. |
| Model dir | `~/ai/omlx-models/<role>/` holds exactly one symlink to the weights. The model id clients see is that directory name (e.g. `orchestrator-qwen36-35b-a3b-oq4e-mtp`), not an absolute path. |
| Admin key | `~/ai/omlx/omlx.key` (mode 600, generated on first start). Needed only for the admin API; inference is keyless for the stack's clients (`allow_unauthenticated_inference`, persisted in `~/.omlx/settings.json`). |
| Logs | `~/ai/logs/<role>.log`, same as before. MTP acceptance rates are logged per request (`MTP[n] ... accept=`). |
| Settings | `~/.omlx/settings.json` per user. The launcher pins the model, sets the 8192 default `max_tokens`, and pre-loads it. |

Unknown model ids get a 404; oMLX never loads weights a client names (mlx_lm.server did, which is
why the meter pins `METER_*_MODEL`).

## Useful commands

```bash
# What a role serves
curl -s http://127.0.0.1:8001/v1/models
# Per-model settings (MTP, thinking, pin) — needs the admin key
KEY=$(cat ~/ai/omlx/omlx.key)
curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8001/admin/api/models | python3 -m json.tool | less
# Turn MTP off/on for a model (triggers a reload; requests get 409 for a few seconds)
curl -s -X PUT -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"mtp_enabled": false}' http://127.0.0.1:8001/admin/api/models/<model-id>/settings
```

Thinking is controlled per request exactly as before (`chat_template_kwargs: {"enable_thinking": false}`);
with thinking on, the answer comes back in `content` and the reasoning in `reasoning`.

## Rollback

```bash
# M1 orchestrator
launchctl setenv LOCAL_AI_SERVER mlx_lm   # or add LOCAL_AI_SERVER=mlx_lm to the plist's EnvironmentVariables
launchctl kickstart -k gui/$(id -u)/com.localai.orchestrator
# M2 workers: put LOCAL_AI_SERVER=mlx_lm in ~/ai/local-ai-stack/.env, then kill the listener;
# launchd's KeepAlive restarts it through start-<role>-mlx_lm.sh
kill $(lsof -ti tcp:8002 -sTCP:LISTEN)
```
Then set `METER_*_MODEL` in `~/ai/dashboard/dashboard.env` back to the absolute model paths and
kickstart `com.localai.dashboard.meter`.

## Upgrading oMLX

```bash
cd ~/ai/omlx && uv pip install --python .venv/bin/python <new wheel url>
```
Re-run the gates before relying on it: `src/toolcalleval` and `src/modeleval` in the dashboard
repo, and a soak (`scripts/bench-chat-endpoint.sh` or an 8-client loop) watching RSS.
