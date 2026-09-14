# 2026-09-14 — Watch mlx-lm PR #1788 (Qwen3.8-Flash-Next) in the blocker watcher

Track C of `plans/2026-09-14-runtime-main-trial-and-optiq-eval.md`, split out so it can be
executed on its own. **Scope is this one script and its doc line. Nothing else.**

## Goal

`scripts/check-mlx-blockers.sh` notifies when mlx-lm PR #1788 (support for the `qwen4_exp`
architecture, i.e. Qwen3.8-Flash-Next) is merged, the same way it already does for PR #1410
and `deepseek_v4.py`.

## Non-goals

- No change to the weekly cadence, the state-file/notify mechanism, or the exit-code contract
  (0 unchanged · 10 something unblocked · 1 could not check).
- No change to how PR #1410, `deepseek_v4.py`, or the PyPI release are checked.
- No download of Flash-Next weights. No launcher, plist, or meter change.
- Do not touch `scripts/m2-watchdog.sh`, `scripts/start-*.sh`, or anything under `configs/`.

## Current system

`scripts/check-mlx-blockers.sh` (bash, `set -uo pipefail`) runs weekly from
`configs/launchd/com.localai.mlx-blocker-watch.plist.template`. It:

1. Queries the GitHub API for PR #1410's state (`merged` / `open` / `closed`), whether
   `mlx_lm/models/deepseek_v4.py` exists on `main`, and the latest `mlx-lm` version on PyPI.
2. Exits 1 if any of the three came back empty.
3. Builds `current="pr1410=$pr_state deepseek_v4=$dsv4 mlx-lm=$latest"`, logs it, compares with
   `$STATE_FILE`, and returns 0 silently when unchanged.
4. Collects `news+=(...)` lines for each unblocked item and, if any, writes the state file,
   logs `NOTIFY: …`, calls `launchpad notify`, and exits 10.

Why Flash-Next matters (from the research of 2026-09-14): Qwen3.8-Flash-Next is 125B total /
6B active and beats the currently served Qwen3.8-27B on every coding benchmark (SWE-bench Pro
62.5 vs 61.7, DeepSWE 58.7 vs 42.2, SWE-bench Multilingual 81.0 vs 73.8, LiveCodeBench v6
91.9 vs 90.3). It would replace all three roles. It needs `mlx_lm/models/qwen4_exp.py`, which
is [PR #1788](https://github.com/ml-explore/mlx-lm/pull/1788) — open as of 2026-09-14.

## Proposed change

Add a fourth probe, structured exactly like the PR #1410 one:

```bash
pr1788="$(api https://api.github.com/repos/ml-explore/mlx-lm/pulls/1788 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("merged" if d.get("merged") else d.get("state","?"))' 2>/dev/null)"
```

- Include `pr1788` in the empty-check that exits 1, and in the `CHECK FAILED` log line.
- Append `pr1788=$pr1788` to `current` (order: after `deepseek_v4=`, before `mlx-lm=`).
- Add `[ "$pr1788" = "merged" ] && news+=("Qwen3.8-Flash-Next: mlx-lm PR #1788 merged")`.
- Update the header comment block: a third bullet for Qwen3.8-Flash-Next / PR #1788 /
  `qwen4_exp`, and note that these weights are **not** on disk (unlike the other two).
- Change the notify message's trailing pointer from
  `Weights are already on disk — see plans/2026-08-09-model-refresh.md` to
  `See plans/2026-08-09-model-refresh.md and plans/2026-09-14-runtime-main-trial-and-optiq-eval.md`
  (the "already on disk" claim is no longer true for every item).

Because `current` gains a field, the first run after deploy will differ from the stored state
and rewrite the state file; with PR #1788 still open there is no news, so it exits 0 without
notifying. That is the intended behaviour.

## Files expected to change

- `scripts/check-mlx-blockers.sh`
- `docs/OPERATIONS.md` — the watcher is not documented anywhere yet. Add a short section
  "Upstream blocker watch" (5–8 lines): what it watches (PR #1410, `deepseek_v4.py`, PR #1788,
  PyPI release), cadence (weekly, `com.localai.mlx-blocker-watch`), where it logs
  (`~/ai/logs/mlx-blockers.log`), and how to run it by hand.

## Step-by-step implementation tasks

1. Edit `scripts/check-mlx-blockers.sh` as described in "Proposed change".
2. `bash -n scripts/check-mlx-blockers.sh`.
3. Run it against a scratch state file so the real weekly state is untouched:
   `MLX_WATCH_STATE=/tmp/mlx-blockers.test.state MLX_WATCH_LOG=/tmp/mlx-blockers.test.log bash scripts/check-mlx-blockers.sh; echo "exit=$?"`
   Expect `exit=0` and a log line containing `pr1410=open deepseek_v4=absent pr1788=open mlx-lm=0.31.3`
   (the exact PR states may differ if upstream moved — that is fine, but the field must be present).
4. Simulate a merge to prove the notify path works without touching GitHub: run with the `api`
   function overridden, e.g. by a tiny wrapper script that `source`s a fake `api()` returning
   `{"merged": true}` for the 1788 URL — or, simpler and acceptable, temporarily `sed` the PR
   number in a copy of the script under `/tmp` to a known-merged PR (`1801`, merged 2026-09-01)
   and confirm `exit=10` and a `NOTIFY:` line naming Qwen3.8-Flash-Next. Do not commit the copy.
5. Update `docs/OPERATIONS.md`.
6. Commit with a conventional message (`feat(watch): notify when mlx-lm PR #1788 (Flash-Next) merges`).

## Acceptance criteria

- `bash -n` clean.
- Real run (step 3) exits 0 and logs a state string containing `pr1788=`.
- Simulated-merge run (step 4) exits 10 and logs `NOTIFY:` with `Qwen3.8-Flash-Next`.
- A run with the network unreachable (e.g. `api() { false; }` override) still exits 1 with
  `CHECK FAILED`, i.e. the new field did not weaken the empty-check.
- `git diff --stat` touches only the two files listed above.

## Test plan (exact commands)

```bash
bash -n scripts/check-mlx-blockers.sh
MLX_WATCH_STATE=/tmp/mlx-blockers.test.state MLX_WATCH_LOG=/tmp/mlx-blockers.test.log \
  bash scripts/check-mlx-blockers.sh; echo "exit=$?"; tail -2 /tmp/mlx-blockers.test.log
sed 's#pulls/1788#pulls/1801#' scripts/check-mlx-blockers.sh > /tmp/check-merged.sh
MLX_WATCH_STATE=/tmp/mlx-blockers.test2.state MLX_WATCH_LOG=/tmp/mlx-blockers.test2.log \
  bash /tmp/check-merged.sh; echo "exit=$?"; tail -2 /tmp/mlx-blockers.test2.log
python3 -m pytest tests/ -q     # existing suite must stay green (it does not cover this script)
```

## Rollback plan

`git revert` the one commit. The state file gains a field but nothing reads it except this
script, so an older script simply sees a changed string and rewrites it; no notify fires because
no `news` line is true.

## Documentation updates

- `docs/OPERATIONS.md`: new "Upstream blocker watch" section as described under "Files
  expected to change".

## Risks and edge cases

- GitHub API rate limit (60/h unauthenticated): one more call per weekly run — negligible.
- If PR #1788 is closed unmerged and superseded by another PR, the watcher will report `closed`
  forever; that is the same limitation the #1410 probe already has and is acceptable.
- The `sed` simulation in step 4 must run from `/tmp`, never overwrite the real script, and
  must use a scratch `MLX_WATCH_STATE` so the real weekly state does not record a false merge.
