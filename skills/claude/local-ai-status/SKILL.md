---
name: local-ai-status
description: Check whether the local AI stack endpoints and MCP bridge are working. Use when the user asks about local AI status or a local model call fails.
allowed-tools: mcp__local-ai-delegate__local_ai_status, Bash(curl *), Bash(lsof *), Bash(ifconfig *), Bash(ping *), Bash(pwd)
---

Check local AI infrastructure status.

1. Call `mcp__local-ai-delegate__local_ai_status`.
2. If an endpoint is down, launchd owns the services, so suggest a launchd check or restart.
   Do not suggest `scripts/start-*.sh`: those are manual-mode launchers.
   Always use `127.0.0.1`, never `localhost`: a Docker container can answer on `localhost`.
   - Machine 1 Orchestrator: `launchctl print "gui/$(id -u)/com.localai.orchestrator" | grep -E 'state|pid|last exit'`,
     then `launchctl kickstart -k "gui/$(id -u)/com.localai.orchestrator"` to restart.
   - Machine 2 workers (`com.localai.developer`, `com.localai.reviewer`):
     `ssh admin@10.10.10.2 'sudo launchctl print system/com.localai.developer | grep -E "state|pid|last exit"'`.
     The Machine 1 watchdog (`com.localai.m2-watchdog`) restarts wedged workers on its own.
   - If both Machine 2 endpoints time out, check the link first:
     `ifconfig bridge0 | grep status` and `ping -c1 -t2 10.10.10.2`.
     If the bridge is inactive or the ping fails, ssh and the watchdog cannot help.
     Say that Machine 2 or its Thunderbolt cable needs attention.
   - When Machine 2 is down, `local_review` still works because it uses the Orchestrator
     on Machine 1. `run_local_plan` does not work: it needs the Developer and the Reviewer.
   - Details: `~/Developer/server-setup/docs/OPERATIONS.md`.
3. Do not attempt destructive fixes automatically.
4. Report concise status and next action.

Request: $ARGUMENTS
