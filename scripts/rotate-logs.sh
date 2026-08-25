#!/usr/bin/env bash
set -uo pipefail

# Trim the always-on stack's logs. Installed as a daily launchd agent (com.localai.log-rotate).
#
# COPY-TRUNCATE, not rename: mlx_lm.server, the meter and the collector hold their log open for the
# life of the process. Renaming the file would leave every one of them appending to an inode nobody
# can see, and the visible log would stay empty until the next restart. Copying then truncating in
# place keeps their file descriptors valid.
#
# Keeps exactly one previous copy per log (<name>.1), overwritten each rotation.
# Env overrides: LOG_DIR, EXTRA_LOG_DIRS (colon-separated), MAX_BYTES.

LOG_DIR="${LOG_DIR:-$HOME/ai/logs}"
# OpenCode writes one unrotated file and never trims it: found at 374 MB on 2026-08-25, most of it
# 137,653 "duplicate skill name" warnings emitted on every start. Same copy-truncate reasoning as
# above — the running process holds the file open.
EXTRA_LOG_DIRS="${EXTRA_LOG_DIRS:-$HOME/.local/share/opencode/log}"
MAX_BYTES="${MAX_BYTES:-52428800}"   # 50 MB

rotate_dir() {
  local dir="$1" log size
  [ -d "$dir" ] || return 0   # nothing logged yet — not an error
  for log in "$dir"/*.log; do
    [ -f "$log" ] || continue                       # no matches: the glob stays literal
    size=$(stat -f%z "$log" 2>/dev/null || echo 0)
    [ "$size" -gt "$MAX_BYTES" ] || continue
    cp "$log" "$log.1" && : > "$log" &&
      printf '%s  rotated %s (%s bytes)\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$(basename "$log")" "$size"
  done
}

rotate_dir "$LOG_DIR"
# Split on ':' without leaking IFS into anything that runs after this loop.
while IFS= read -r extra; do
  [ -n "$extra" ] && rotate_dir "$extra"
done <<< "$(printf '%s' "$EXTRA_LOG_DIRS" | tr ':' '\n')"
exit 0
