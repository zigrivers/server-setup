# Plan: Watch required MMR routes

## Goal

Make the existing M1 watchdog verify the two meter routes required by MMR:
`opencode-glm` on port 9004 and `opencode-local` on port 9006. Reuse the
existing two-failure debounce, cooldown, meter restart, logging, and desktop
notification behavior.

## Non-goals

- Do not add another watchdog or monitoring service.
- Do not send paid inference requests.
- Do not change MMR channel routing, provider credentials, or model selection.
- Do not change Machine 2 launch daemons.
- Do not restart any live service until implementation is approved and tests pass.

## Current system summary

`scripts/m2-watchdog.sh` runs every 60 seconds through
`com.localai.m2-watchdog`. It checks Machine 2 ports 8002 and 8003 directly,
then checks meter ports 9002 and 9003 through `/v1/models`. Two consecutive
meter failures trigger a cooldown-gated restart of
`com.localai.dashboard.meter`.

MMR uses two additional meter routes which the watchdog does not check:

- `opencode-glm`: `http://127.0.0.1:9004/v1`
- `opencode-local`: `http://127.0.0.1:9006/v1`

Both routes returned HTTP 200 from `/v1/models` on 2026-08-08. A real MMR run
also completed both channels. Current health is good; automatic detection is
the remaining gap.

## Proposed architecture

Extend the existing default `METER_PORTS` value from `9002 9003` to
`9002 9003 9004 9006`. Keep the existing environment override so a host can
exclude an intentionally disabled optional route without changing code.

Use the existing `/v1/models` probe. It verifies route availability without
buying tokens. Keep the existing two-tick debounce and one meter restart path.

This is the smallest change because all required recovery behavior already
exists in the watchdog.

## Files expected to change

- `scripts/m2-watchdog.sh` — include ports 9004 and 9006 in the default meter
  probe list and update the nearby description.
- `tests/test_m2_watchdog_notify.py` or one adjacent watchdog test file — prove
  the default probe list includes both required MMR routes without performing
  real network calls.
- `docs/OPERATIONS.md` — document watched meter routes and the `METER_PORTS`
  override for intentionally disabled providers.

## Implementation tasks

1. Add a failing test which records attempted `/v1/models` ports and expects
   9002, 9003, 9004, and 9006.
2. Change the default `METER_PORTS` list and its comment.
3. Document the routes and override.
4. Run focused tests and shell lint.
5. Run the repository test suite.
6. With approval, reinstall only the watchdog LaunchAgent.
7. Verify one healthy tick exits zero and performs no restart.
8. Verify ports 9004 and 9006 still return HTTP 200.

## Acceptance criteria

- Default watchdog execution probes ports 9002, 9003, 9004, and 9006.
- A healthy run exits zero and does not restart the meter.
- One failed meter tick records failure without restart.
- Two consecutive failed ticks use the existing cooldown-gated meter restart.
- `METER_PORTS` still overrides the default list.
- `/v1/models` is the only MMR route probe; no paid completion runs.
- Live ports 9004 and 9006 return HTTP 200 after installation.
- `mmr doctor` reports `opencode-glm` and `opencode-local` ready.

## Test plan

Run:

```bash
pytest -q tests/test_m2_watchdog_notify.py tests/test_m2_watchdog_routes.py
shellcheck scripts/m2-watchdog.sh scripts/install-launchd-machine1.sh
pytest -q
```

After approval to update the live LaunchAgent:

```bash
scripts/install-launchd-machine1.sh m2-watchdog
M2_WATCHDOG_DRYRUN=1 scripts/m2-watchdog.sh
curl -fsS http://127.0.0.1:9004/v1/models >/dev/null
curl -fsS http://127.0.0.1:9006/v1/models >/dev/null
mmr doctor
```

Inspect the watchdog log and `launchctl print` to confirm zero unexpected
restarts.

## Rollback plan

Revert the source commit. Reinstall only the watchdog LaunchAgent with
`scripts/install-launchd-machine1.sh m2-watchdog`. The previous 9002 and 9003
coverage returns immediately. No data migration or credential change exists.

## Documentation updates required

Update `docs/OPERATIONS.md` with the watched routes, their purpose, and the
`METER_PORTS` override.

## Risks and edge cases

- Port 9004 depends on the GLM provider key and network access. If that channel
  is intentionally disabled, set `METER_PORTS="9002 9003 9006"` in the
  LaunchAgent instead of accepting restart alerts.
- `/v1/models` proves the route responds, not that paid inference succeeds.
  MMR's real channel run remains the end-to-end proof.
- Restarting the shared meter briefly interrupts all proxied routes. Existing
  two-tick debounce and cooldown limit this risk.
- A route can fail while Machine 2 remains healthy. The existing meter-only
  recovery branch already handles this state.
