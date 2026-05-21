#!/usr/bin/env bash
set -euo pipefail

# Manual-mode launcher. Normally launchd owns these via
#   com.localai.developer and com.localai.reviewer  (LaunchDaemons on M2).
# Use this script only when you've intentionally booted the launchd
# daemons out (e.g. during debugging).

REPO_DIR="${LOCAL_AI_REPO:-$HOME/ai/local-ai-stack}"
"$REPO_DIR/scripts/start-developer.sh" &
DEV_PID=$!
"$REPO_DIR/scripts/start-reviewer.sh" &
REV_PID=$!

echo "Developer  pid=$DEV_PID  log=$HOME/ai/logs/developer.log"
echo "Reviewer   pid=$REV_PID  log=$HOME/ai/logs/reviewer.log"
echo "Note: these run in the background; launchd is not supervising them."
