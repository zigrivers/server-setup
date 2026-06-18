#!/usr/bin/env bash
set -euo pipefail
# One-command project ingester for the RAG proxy.
#   scripts/rag-add-project.sh <project-name-or-path>
# Resolves a project under ~/Developer, ingests its code+docs into a Qdrant collection named after the
# project (no-downtime sync), and calibrates a per-collection gate. Re-run any time to refresh.
#
# Source files come from `git ls-files` when the project is a git repo (respects .gitignore, sees only
# tracked source); otherwise from `find` with directory prunes. Filtered by an extension allowlist, an
# exclude list, a size cap, and a binary check. Counts are reported — nothing is silently dropped.

VENV_PY="${VENV_PY:-$HOME/ai/local-ai-stack/.venv/bin/python}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_ROOT="${DEV_ROOT:-$HOME/Developer}"
MAX_BYTES="${RAG_MAX_FILE_BYTES:-200000}"

if [ $# -lt 1 ]; then
  echo "usage: rag-add-project.sh <project-name-or-path>" >&2
  exit 1
fi

ARG="$1"
if [ -d "$ARG" ]; then
  PROJ="$(cd "$ARG" && pwd)"
elif [ -d "$DEV_ROOT/$ARG" ]; then
  PROJ="$(cd "$DEV_ROOT/$ARG" && pwd)"
else
  echo "project not found: '$ARG' (looked at '$ARG' and '$DEV_ROOT/$ARG')" >&2
  exit 1
fi
NAME="$(basename "$PROJ")"

echo "==> Ingesting '$NAME' from $PROJ into collection '$NAME'"

# Extension allowlist (regex, anchored at end).
EXT_RE='\.(md|txt|ts|tsx|js|jsx|py|sh|json|yaml|yml)$'
# Path-fragment excludes (any match drops the file).
EXCLUDE_RE='(^|/)(node_modules|\.git|dist|build|\.next|\.turbo|coverage|vendor|\.venv|__pycache__)(/|$)|\.lock$|\.min\.(js|css)$|(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock)$'

# Enumerate candidate files as absolute paths.
list_files() {
  if git -C "$PROJ" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$PROJ" ls-files -z | while IFS= read -r -d '' rel; do printf '%s\0' "$PROJ/$rel"; done
  else
    find "$PROJ" -type d \( -name node_modules -o -name .git -o -name dist -o -name build \
      -o -name .next -o -name .turbo -o -name coverage -o -name vendor -o -name .venv \
      -o -name __pycache__ \) -prune -o -type f -print0
  fi
}

SCANNED=0; KEPT=0; SKIP_EXT=0; SKIP_EXCL=0; SKIP_BIG=0; SKIP_BIN=0
FILELIST="$(mktemp)"
trap 'rm -f "$FILELIST"' EXIT

while IFS= read -r -d '' f; do
  SCANNED=$((SCANNED+1))
  [[ "$f" =~ $EXT_RE ]] || { SKIP_EXT=$((SKIP_EXT+1)); continue; }
  [[ "$f" =~ $EXCLUDE_RE ]] && { SKIP_EXCL=$((SKIP_EXCL+1)); continue; }
  sz=$(stat -f%z "$f" 2>/dev/null || echo 0)
  [ "$sz" -gt "$MAX_BYTES" ] && { SKIP_BIG=$((SKIP_BIG+1)); continue; }
  grep -Iq . "$f" 2>/dev/null || { SKIP_BIN=$((SKIP_BIN+1)); continue; }   # -I: skip binary
  printf '%s\n' "$f" >> "$FILELIST"
  KEPT=$((KEPT+1))
done < <(list_files)

echo "    scanned=$SCANNED kept=$KEPT  (skipped: ext=$SKIP_EXT excluded=$SKIP_EXCL toobig=$SKIP_BIG binary=$SKIP_BIN)"
if [ "$KEPT" -eq 0 ]; then
  echo "    nothing to ingest — aborting" >&2
  exit 1
fi

# Ingest (no-downtime sync: upsert current files, delete points for vanished files).
COLLECTION="$NAME" "$VENV_PY" "$REPO_DIR/scripts/rag-ingest.py" --stdin --sync-paths < "$FILELIST"

# Calibrate the per-collection gate and write its config.
COLLECTION="$NAME" "$VENV_PY" "$REPO_DIR/scripts/rag-calibrate.py" "$NAME"

echo "==> Done. Point a project at RAG by setting its api-key to '$NAME' against the proxy on :9200."
echo "    Turn RAG off for it later: curl -X DELETE \$QDRANT_URL/collections/$NAME"
