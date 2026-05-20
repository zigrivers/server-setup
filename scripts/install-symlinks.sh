#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$HOME/ai/bin"

ln -sfn "$REPO_DIR/scripts/start-orchestrator.sh" "$HOME/ai/bin/start-orchestrator.sh"
ln -sfn "$REPO_DIR/scripts/stop-orchestrator.sh" "$HOME/ai/bin/stop-orchestrator.sh"
ln -sfn "$REPO_DIR/scripts/m1-ai-status.sh" "$HOME/ai/bin/m1-ai-status.sh"
ln -sfn "$REPO_DIR/scripts/start-worker-models.sh" "$HOME/ai/bin/start-worker-models.sh"
ln -sfn "$REPO_DIR/scripts/stop-worker-models.sh" "$HOME/ai/bin/stop-worker-models.sh"
ln -sfn "$REPO_DIR/scripts/m2-ai-status.sh" "$HOME/ai/bin/m2-ai-status.sh"
ln -sfn "$REPO_DIR/scripts/bench-chat-endpoint.sh" "$HOME/ai/bin/bench-chat-endpoint.sh"
ln -sfn "$REPO_DIR/scripts/smoke-test-endpoints.sh" "$HOME/ai/bin/smoke-test-endpoints.sh"
ln -sfn "$REPO_DIR/scripts/preflight.sh" "$HOME/ai/bin/preflight.sh"

echo "Symlinks installed in $HOME/ai/bin. Add this to PATH if needed:"
echo 'export PATH="$HOME/ai/bin:$PATH"'
