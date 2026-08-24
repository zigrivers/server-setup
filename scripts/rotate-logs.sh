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
# Env overrides: LOG_DIR, MAX_BYTES.

LOG_DIR="${LOG_DIR:-$HOME/ai/logs}"
MAX_BYTES="${MAX_BYTES:-52428800}"   # 50 MB

[ -d "$LOG_DIR" ] || exit 0   # nothing logged yet — not an error

for log in "$LOG_DIR"/*.log; do
  [ -f "$log" ] || continue                       # no matches: the glob stays literal
  size=$(stat -f%z "$log" 2>/dev/null || echo 0)
  [ "$size" -gt "$MAX_BYTES" ] || continue
  cp "$log" "$log.1" && : > "$log" &&
    printf '%s  rotated %s (%s bytes)\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$(basename "$log")" "$size"
done
exit 0
