#!/usr/bin/env bash
set -uo pipefail

# Preflight check from Machine 1 against the full split-machine stack.
# Verifies:
#   1. Thunderbolt Bridge reachability (ping 10.10.10.2)
#   2. SSH to Machine 2 works
#   3. hf CLI is installed and authenticated
#   4. M1 venv exists and is importable
#   5. Orchestrator endpoint responds (127.0.0.1:8001/v1/models)
#   6. Developer endpoint responds (10.10.10.2:8002/v1/models)
#   7. Reviewer endpoint responds (10.10.10.2:8003/v1/models)
#   8. .env exists and has the three *_BASE_URL keys
#
# Exits 0 if every check passes; non-zero otherwise. Each line of output
# starts with [ok] or [fail] so it's easy to grep.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
M2_HOST="${M2_HOST:-10.10.10.2}"
M2_USER="${M2_USER:-admin}"

fail=0
pass()  { printf '[ok]   %s\n' "$1"; }
warn()  { printf '[warn] %s\n' "$1"; }
nope()  { printf '[fail] %s\n' "$1"; fail=1; }

echo "=== preflight: $(date) ==="
echo "Repo: $REPO_DIR"
echo "M2:   $M2_USER@$M2_HOST"
echo

# 1. Thunderbolt reachability
if ping -c 1 -W 1000 "$M2_HOST" >/dev/null 2>&1; then
  pass "ping $M2_HOST"
else
  nope "ping $M2_HOST — Thunderbolt Bridge IPs probably wrong"
fi

# 2. SSH to M2 (BatchMode so it fails fast on auth issues)
if ssh -o BatchMode=yes -o ConnectTimeout=5 "$M2_USER@$M2_HOST" 'echo ssh-ok' 2>/dev/null | grep -q ssh-ok; then
  pass "ssh $M2_USER@$M2_HOST"
else
  warn "ssh $M2_USER@$M2_HOST failed (try: ssh-copy-id $M2_USER@$M2_HOST)"
fi

# 3. hf CLI auth
if command -v hf >/dev/null 2>&1; then
  if hf auth whoami >/dev/null 2>&1; then
    pass "hf auth whoami"
  else
    nope "hf CLI present but not authenticated (run: hf auth login)"
  fi
else
  nope "hf CLI not on PATH (activate the repo venv first)"
fi

# 4. M1 venv
if [ -f "$REPO_DIR/.venv/bin/python" ]; then
  if "$REPO_DIR/.venv/bin/python" -c 'import local_ai_stack' 2>/dev/null; then
    pass "local_ai_stack importable in $REPO_DIR/.venv"
  else
    nope "local_ai_stack not importable — re-run: uv pip install -e '.[all]'"
  fi
else
  nope "$REPO_DIR/.venv missing — re-run: uv venv .venv --python 3.12"
fi

# 5-7. Endpoints
check_endpoint() {
  local name="$1" url="$2"
  if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
    pass "$name endpoint $url"
  else
    nope "$name endpoint $url unreachable"
  fi
}
check_endpoint "orchestrator" "http://127.0.0.1:8001/v1/models"
check_endpoint "developer"    "http://$M2_HOST:8002/v1/models"
check_endpoint "reviewer"     "http://$M2_HOST:8003/v1/models"

# 8. .env keys
if [ -f "$REPO_DIR/.env" ]; then
  missing=0
  for key in ORCH_BASE_URL DEV_BASE_URL REVIEW_BASE_URL ORCH_MODEL DEV_MODEL REVIEW_MODEL; do
    if ! grep -Eq "^$key=" "$REPO_DIR/.env"; then
      nope ".env missing $key"
      missing=1
    fi
  done
  if [ "$missing" = 0 ]; then
    pass ".env has all required keys"
  fi
else
  nope "$REPO_DIR/.env not found (cp configs/env.machine1.example .env)"
fi

echo
if [ "$fail" = 0 ]; then
  echo "=== preflight: PASS ==="
  exit 0
else
  echo "=== preflight: FAIL ==="
  exit 1
fi
