# MCP Bridge — `local-ai-delegate`

The MCP bridge lets Claude Code and Codex hand work off to the local
multi-agent stack without giving them shell access to the rest of the
machine. It exposes three tools over stdio.

Source: `mcp/local_delegate_mcp/server.py`.

## Tools

### `local_ai_status() -> str`

Pings each of the three local endpoints (`ORCH_BASE_URL`, `DEV_BASE_URL`,
`REVIEW_BASE_URL`) at `/models` and returns one line per service:

```text
orchestrator: OK http://127.0.0.1:8001/v1/models HTTP 200
developer:    OK http://10.10.10.2:8002/v1/models HTTP 200
reviewer:     FAIL http://10.10.10.2:8003/v1/models URLError: ...
```

Safe to call without authorization.

### `git_local_summary(workspace: str = ".") -> str`

Runs `git status --short` and `git diff --stat` in the given workspace
and returns the combined output (truncated to 20 KB).

The `workspace` argument is resolved against the configured allowed
roots (see below) and must be inside one of them.

### `run_local_plan(plan_file, workspace=".", in_place=False, timeout_minutes=60) -> str`

The heavy tool. Invokes the `local-exec-plan` console script against the
given plan file and workspace. Captures the last 30 KB of stdout/stderr
and returns it with the exit code.

By default a new git worktree is created next to the workspace
(`<repo>-local-<feature-slug>-<timestamp>` on branch
`ai/local/<feature-slug>-<timestamp>`). Pass `in_place=true` to operate
in the current worktree.

Default timeout is 60 minutes; raise it for long-running plans, but be
aware of Codex/Claude side-channel timeouts.

## Allowed roots

The MCP server refuses to operate outside a configured allowed root.
Configure via environment when registering the server (see
`scripts/register-mcp-claude.sh` and `scripts/register-mcp-codex.sh`):

```text
LOCAL_AI_ALLOWED_ROOTS=$HOME/ai/workspaces:$HOME/code:$HOME/Developer:$HOME/projects:<repo>
LOCAL_AI_DEFAULT_WORKSPACE=$HOME/ai/workspaces
```

`LOCAL_AI_ALLOWED_ROOTS` is a colon-separated list. Each entry is
resolved through `~` expansion and then realpath. If `workspace="."` or
empty is passed, `LOCAL_AI_DEFAULT_WORKSPACE` is used.

If no allowed roots are configured **and** none of the default fallbacks
(`~/ai/workspaces`, `~/code`, `~/Developer`, `~/projects`) exist, every
call to `git_local_summary` / `run_local_plan` fails with a clear error.

## Endpoint configuration

The three base URLs default to the split-machine layout:

```text
ORCH_BASE_URL=http://127.0.0.1:8001/v1
DEV_BASE_URL=http://10.10.10.2:8002/v1
REVIEW_BASE_URL=http://10.10.10.2:8003/v1
```

Override in the same env block passed to `claude mcp add` / `codex mcp add`.

## Locating `local-exec-plan`

The MCP server hunts for the executable in this order:

1. `LOCAL_EXEC_PLAN_BIN` env var (explicit override; recommended).
2. `~/ai/local-ai-stack/.venv/bin/local-exec-plan` (repo layout).
3. `~/ai/bin/local-exec-plan` (legacy / hand-installed layout).

If neither exists, the tool returns the missing-binary error to the
caller. Set `LOCAL_EXEC_PLAN_BIN` explicitly in your MCP registration to
avoid surprises — the `register-mcp-{claude,codex}.sh` scripts already
do this.

## Registering with Claude Code

```bash
cd ~/ai/local-ai-stack
scripts/register-mcp-claude.sh
claude mcp list
```

Inside Claude Code, `/mcp` shows the registered server. Tool calls are
prefixed: `local-ai-delegate__local_ai_status`,
`local-ai-delegate__git_local_summary`,
`local-ai-delegate__run_local_plan`.

The repo's three Claude skills (`delegate-local`, `local-review`,
`local-ai-status`) reference these tools by their prefixed names in their
`allowed-tools` frontmatter.

## Registering with Codex

```bash
cd ~/ai/local-ai-stack
scripts/register-mcp-codex.sh
$EDITOR ~/.codex/config.toml
```

In the `[mcp_servers.local-ai-delegate]` block, set:

```toml
startup_timeout_sec = 20
tool_timeout_sec = 3600
```

The default Codex tool timeout is too short for `run_local_plan`.

## Smoke testing the MCP server directly

```bash
~/ai/local-ai-stack/.venv/bin/python \
  ~/ai/local-ai-stack/mcp/local_delegate_mcp/server.py
```

The server waits for stdio input. Press Ctrl-C — if it started without
ImportError, the server is healthy. To do an actual end-to-end test,
run the HTML guide §14b acceptance flow.

## Security

- The server has no auth: anyone who can speak stdio to the process can
  invoke any tool. That's fine when it's launched by Claude/Codex on
  your own machine.
- `git_local_summary` and `run_local_plan` are confined to
  `LOCAL_AI_ALLOWED_ROOTS`. Do not point those at `/` or your home dir.
- `local_ai_status` makes outbound HTTP calls to the three configured
  endpoints. Keep those endpoints on `127.0.0.1` / Thunderbolt-only.
- See `docs/SECURITY.md` for the full guardrails.
