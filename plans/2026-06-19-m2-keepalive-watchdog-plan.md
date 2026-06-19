# Plan: M2 keep-alive + M1 watchdog (never-sleep, auto-recover)

Date: 2026-06-19
Status: DRAFT (awaiting approval)
Scope: operational reliability for Machine 2 (inference worker). No change to model serving or the
two-machine architecture.

## Goal

M2 (`10.10.10.2`) stays awake and reachable as a 24/7 worker; if it ever drops, the system
auto-recovers without manual intervention; and M1 can manage/inspect M2 over SSH.

## Background (today's incident)

M2 went to sleep → its Thunderbolt-bridge link dropped → `EHOSTUNREACH` from M1. On wake, M2 was
fine but the long-lived **meter** held stale connection state and returned 502 to M2 until restarted.
Root cause: **M2 slept.** Confirmed: ping/direct-worker fine once awake; meter recovered on
`launchctl kickstart`. So the durable fix is (a) prevent sleep, (b) auto-clear a wedged meter, (c)
best-effort wake if it ever sleeps anyway.

## Non-goals

- Waking a **powered-off** M2 (WoL only wakes from sleep, and only if the NIC honors it).
- Changing worker model configs, ports, or the bridge addressing.
- Any exposure beyond the private Thunderbolt link / loopback.

## Components

**A. M2 anti-sleep (`pmset`)** — applied over SSH:
```
sudo pmset -a sleep 0 disksleep 0 powernap 0 lidwake 0 womp 1
```
`sleep 0` (never idle-sleep), `powernap 0` (no half-wakes that flap the link), `womp 1`
(wake-on-magic-packet, required for component D's best-effort wake). Verify `pmset -g | grep " sleep"`
→ `0`. Laptop-in-clamshell caveat: add `disablesleep 1` (AC only) if lid-closed sleep is a factor.

**B. M2 caffeinate LaunchAgent** — belt-and-suspenders, survives reboot and `pmset` resets:
- `configs/launchd/com.localai.caffeinate.plist.template` → `~/Library/LaunchAgents` on M2.
- Runs `/usr/bin/caffeinate -dimsu` (assert no idle/display/disk/system sleep) with `RunAtLoad` +
  `KeepAlive`. gui-domain LaunchAgent, matching the existing `com.localai.developer/reviewer` agents
  (M2 already auto-logs-in and loads those), so no `sudo`/LaunchDaemon needed.

**C. M1 → M2 SSH key** — passwordless management (user authorizes M1's `id_ed25519` via `ssh-copy-id`,
one time). Enables A/B to be applied remotely and the watchdog to restart M2-side services if needed.

**D. M1 watchdog LaunchAgent** — detect + recover:
- `scripts/m2-watchdog.sh` (M1) on a `StartInterval` (60 s) LaunchAgent
  `configs/launchd/com.localai.m2-watchdog.plist.template`.
- Each tick: TCP-probe `10.10.10.2:8002` and `:8003` (short timeout). If both healthy → log OK, exit.
- On failure (with a small state file to debounce, so it acts on a *transition*, not every tick):
  1. Send a **wake-on-LAN** magic packet to M2's MAC (`scripts/wol-m2.sh`, broadcast on bridge0) —
     best-effort wake (needs `womp 1`).
  2. Wait ~5 s; if M2 is reachable but the meter is wedged, `launchctl kickstart -k` the meter
     (the exact fix that worked today).
  3. Re-probe; log result to `~/ai/logs/m2-watchdog.log`; on a down→up or up→down transition, fire
     `launchpad notify` so the user knows.
- Hard guardrails: never act more than once per N ticks (anti-thrash); WoL/kickstart only — never any
  destructive command; if still down after recovery attempts, just keep logging + notify (no loop).

## Files expected to change (server-setup)

- `scripts/setup-m2-keepalive.sh` — orchestrates A+B over SSH (idempotent; verifies after).
- `configs/launchd/com.localai.caffeinate.plist.template` — M2 caffeinate agent.
- `scripts/m2-watchdog.sh` — M1 probe + recover.
- `scripts/wol-m2.sh` — send WoL magic packet to M2 over bridge0.
- `configs/launchd/com.localai.m2-watchdog.plist.template` — M1 watchdog agent.
- `scripts/install-launchd-machine1.sh` — add `m2-watchdog` to the installer.
- `docs/OPERATIONS.md` + `docs/TROUBLESHOOTING.md` — "M2 dropped / won't stay awake" runbook.

Scripts are symlinked into `~/ai/local-ai-stack/scripts` per repo convention; launchd templates are
rendered to real plists by the installer.

## Implementation order

1. (User) authorize SSH key (component C). Verify passwordless `ssh M2 true`.
2. Apply A (pmset) over SSH; verify `sleep 0`.
3. Install B (caffeinate agent) on M2; verify it's running (`launchctl print … | grep state`).
4. Build + install D (watchdog + WoL) on M1; verify a healthy tick logs OK and takes no action.
5. Fault-injection test (see below).
6. Docs + commit/push.

## Acceptance criteria

- `ssh kenallred@10.10.10.2 true` succeeds with no password.
- M2 `pmset -g` shows `sleep 0`; caffeinate agent `state = running` on M2.
- Watchdog: a healthy tick logs OK and takes **no** action; nothing thrashes.
- **Fault injection**: stop one M2 worker (or `sudo pmset sleepnow` on M2) → within ~2 min the
  watchdog logs the drop, attempts WoL + meter kickstart, and on recovery logs up + notifies.
- Meter serves `9002/9003` = 200 after a simulated sleep/wake (auto-recovered, no manual restart).
- No secret/credential added anywhere; SSH key is the only new trust, scoped to the private link.

## Test plan

- Watchdog **dry-run** with M2 healthy: asserts "OK, no action."
- **Simulated wedge**: leave M2 up, manually poison the meter (kickstart while M2 mid-sleep is hard
  to script; instead assert the kickstart path runs when a worker port is closed).
- **Simulated sleep**: `ssh M2 'sudo pmset sleepnow'` (with caffeinate temporarily unloaded) →
  observe detect → WoL → recover, or a clear notify if WoL can't wake it.
- Confirm watchdog log rotates/append-only and bounded.

## Rollback

- `launchctl bootout` the watchdog (M1) and caffeinate (M2) agents → back to today's behavior.
- Remove M1's key from M2 `~/.ssh/authorized_keys` to revoke remote access.
- `sudo pmset` restore defaults on M2 if ever desired.
All components are independent; removing any one leaves the others working.

## Risks & edge cases

- **WoL over Thunderbolt bridge may not wake M2** from full sleep (NIC-dependent). Mitigation: the
  primary defense is *preventing* sleep (A+B); WoL is best-effort, and if it fails the watchdog still
  clears a wedged meter and **notifies** the user to wake M2 physically. Documented honestly.
- **Powered-off M2**: nothing software-side can wake it; watchdog notifies only.
- **Thrash**: the state-file debounce ensures the watchdog acts on transitions, not every 60 s tick.
- **SSH trust**: passwordless M1→M2 is new standing access; acceptable on the private TB link, and
  scoped to one key. No agent forwarding, no M2→M1 reverse trust.
- **caffeinate vs battery**: `-dimsu` keeps a laptop awake on battery too; fine for an always-AC
  worker. If M2 is ever on battery, prefer `caffeinate -s` (AC-only assertion).
