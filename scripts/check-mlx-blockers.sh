#!/usr/bin/env bash
set -uo pipefail

# Weekly watch on the two upstream blockers keeping models off this stack (2026-08-09):
#
#   GLM-5.2      needs mlx-lm PR #1410 (DSA cross-layer indexer sharing). GLM-5.2 ships indexer
#                weights on 21 of 78 layers; stock mlx-lm builds one per layer -> 285 missing.
#   DeepSeek-V4  needs an mlx_lm/models/deepseek_v4.py, which does not exist upstream at all.
#
# Both sets of weights are already downloaded (~/ai/models/glm-5.2-4bit on M1,
# ~admin/ai/models/DeepSeek-V4-Flash-4bit on M2), so a merge is the only thing standing between
# here and running them. Notifies once per state CHANGE, not every week, so a quiet week is silent.
#
# Exit codes: 0 nothing changed · 10 something unblocked · 1 could not check (network/API).

BASELINE_MLX_LM="0.31.3"          # the release that lacks both
STATE_FILE="${MLX_WATCH_STATE:-$HOME/ai/dashboard/mlx-blockers.state}"
LOG_FILE="${MLX_WATCH_LOG:-$HOME/ai/logs/mlx-blockers.log}"
mkdir -p "$(dirname "$STATE_FILE")" "$(dirname "$LOG_FILE")"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"; }

api() { curl -sS --max-time 30 -H 'Accept: application/vnd.github+json' "$1"; }

pr_state="$(api https://api.github.com/repos/ml-explore/mlx-lm/pulls/1410 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("merged" if d.get("merged") else d.get("state","?"))' 2>/dev/null)"
dsv4="$(api https://api.github.com/repos/ml-explore/mlx-lm/contents/mlx_lm/models/deepseek_v4.py \
  | python3 -c 'import json,sys; print("present" if json.load(sys.stdin).get("name") else "absent")' 2>/dev/null)"
latest="$(curl -sS --max-time 30 https://pypi.org/pypi/mlx-lm/json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])' 2>/dev/null)"

if [ -z "$pr_state" ] || [ -z "$dsv4" ] || [ -z "$latest" ]; then
  log "CHECK FAILED (pr=${pr_state:-?} deepseek_v4=${dsv4:-?} mlx-lm=${latest:-?}) — network or API problem"
  exit 1
fi

current="pr1410=$pr_state deepseek_v4=$dsv4 mlx-lm=$latest"
previous="$(cat "$STATE_FILE" 2>/dev/null || true)"
log "$current"

news=()
[ "$pr_state" = "merged" ] && news+=("GLM-5.2: mlx-lm PR #1410 merged")
[ "$dsv4" = "present" ] && news+=("DeepSeek-V4: deepseek_v4.py is upstream")
[ "$latest" != "$BASELINE_MLX_LM" ] && news+=("mlx-lm $latest released (was $BASELINE_MLX_LM)")

if [ "$current" = "$previous" ]; then
  exit 0                      # nothing changed since last week — stay quiet
fi
printf '%s\n' "$current" > "$STATE_FILE"

if [ ${#news[@]} -eq 0 ]; then
  exit 0                      # state string moved but nothing actionable (e.g. PR reopened)
fi

msg="Local AI: $(IFS='; '; echo "${news[*]}"). Weights are already on disk — see plans/2026-08-09-model-refresh.md"
log "NOTIFY: $msg"
command -v launchpad >/dev/null 2>&1 && launchpad notify "$msg" >/dev/null 2>&1
exit 10
