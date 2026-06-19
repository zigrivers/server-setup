#!/usr/bin/env bash
set -euo pipefail

# Point the subscription CLIs (Claude Code / Gemini / Codex) at the local otel-usage-bridge so their
# token/cost usage shows in the dashboard as source='reported' rows — WITHOUT proxying their traffic.
#
# Privacy: prompt logging is forced OFF for every CLI, and the bridge stores usage only (never
# content). Endpoint is loopback. Each edited config is backed up first; re-running is idempotent.
#
# Requires the meter started with OTEL_BRIDGE=1 (loopback :4318). NOTE the bridge decodes OTLP/HTTP
# JSON; a CLI that only emits protobuf needs an OTel Collector to translate (see docs/observability.md).

BRIDGE="${OTEL_BRIDGE_ENDPOINT:-http://127.0.0.1:4318}"
bak() { [ -f "$1" ] && cp "$1" "$1.bak.$(date +%s)" && echo "  backed up $1"; }

echo "==> Claude Code (~/.claude/settings.json env block)"
CC="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"
if command -v jq >/dev/null 2>&1; then
  bak "$CC"; [ -f "$CC" ] || echo '{}' > "$CC"
  jq --arg ep "$BRIDGE" '.env = (.env // {}) + {
        CLAUDE_CODE_ENABLE_TELEMETRY:"1", OTEL_METRICS_EXPORTER:"otlp",
        OTEL_EXPORTER_OTLP_PROTOCOL:"http/json", OTEL_EXPORTER_OTLP_ENDPOINT:$ep
      }' "$CC" > "$CC.tmp" && mv "$CC.tmp" "$CC" && echo "  set telemetry env (metrics only; no logs exporter ⇒ no prompts)"
else
  echo "  jq not found — add this to $CC manually:"
  echo '  "env": { "CLAUDE_CODE_ENABLE_TELEMETRY":"1","OTEL_METRICS_EXPORTER":"otlp","OTEL_EXPORTER_OTLP_PROTOCOL":"http/json","OTEL_EXPORTER_OTLP_ENDPOINT":"'"$BRIDGE"'" }'
fi

echo "==> Gemini CLI (~/.gemini/settings.json telemetry block)"
GM="$HOME/.gemini/settings.json"
mkdir -p "$HOME/.gemini"
if command -v jq >/dev/null 2>&1; then
  bak "$GM"; [ -f "$GM" ] || echo '{}' > "$GM"
  jq --arg ep "$BRIDGE" '.telemetry = (.telemetry // {}) + {
        enabled:true, target:"local", otlpProtocol:"http", otlpEndpoint:$ep,
        logPrompts:false, traces:false
      }' "$GM" > "$GM.tmp" && mv "$GM.tmp" "$GM" && echo "  set telemetry (logPrompts=false, traces off)"
else
  echo "  jq not found — add a .telemetry block with enabled/target=local/otlpEndpoint/logPrompts=false manually."
fi

echo "==> Codex (~/.codex/config.toml [otel] block)"
CX="$HOME/.codex/config.toml"
mkdir -p "$HOME/.codex"; touch "$CX"
if ! grep -q '^\[otel\]' "$CX"; then
  bak "$CX"
  {
    echo ""
    echo "[otel]"
    echo "exporter = \"otlp-http\""
    echo "endpoint = \"$BRIDGE\""
    echo "protocol = \"json\""
    echo "log_user_prompt = false"
  } >> "$CX"
  echo "  appended [otel] block (log_user_prompt=false)"
else
  echo "  [otel] already present — leaving as-is (edit endpoint/log_user_prompt manually if needed)"
fi

echo
echo "Done. Start the meter with OTEL_BRIDGE=1, then exercise each CLI; usage appears in the dashboard"
echo "as source='reported' (usage only, no content). Verify the bridge is loopback-only:"
echo "  curl -s -m 3 http://10.10.10.1:4318/v1/metrics  # should refuse from off-machine"
