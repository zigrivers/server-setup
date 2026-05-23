---
name: local-ai-status
description: Check whether the local AI stack endpoints and MCP bridge are working
argument-hint: [optional]
allowed-tools: local-ai-delegate__local_ai_status, Bash(curl *), Bash(lsof *), Bash(pwd)
---

Check local AI infrastructure status.

1. Call `local-ai-delegate__local_ai_status`.
2. If an endpoint is down, suggest the relevant startup script:
   - Machine 1 Orchestrator: `scripts/start-orchestrator.sh`
   - Machine 2 workers: `scripts/start-worker-models.sh`
3. Do not attempt destructive fixes automatically.
4. Report concise status and next action.

Request: $ARGUMENTS
