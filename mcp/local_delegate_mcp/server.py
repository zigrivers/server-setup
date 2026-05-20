from __future__ import annotations

import os
import subprocess
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("local-ai-delegate")


def allowed_roots() -> list[Path]:
    raw = os.environ.get("LOCAL_AI_ALLOWED_ROOTS", "")
    roots: list[Path] = []
    if raw:
        for item in raw.split(":"):
            item = item.strip()
            if item:
                roots.append(Path(item).expanduser().resolve())

    roots.extend(
        [
            Path.home() / "ai" / "workspaces",
            Path.home() / "code",
            Path.home() / "Developer",
            Path.home() / "projects",
        ]
    )
    return [p.resolve() for p in roots if p.exists()]


def resolve_allowed(path: str, *, must_exist: bool = True) -> Path:
    if not path or path == ".":
        path = os.environ.get("LOCAL_AI_DEFAULT_WORKSPACE", ".")
    p = Path(path).expanduser().resolve()
    if must_exist and not p.exists():
        raise ValueError(f"Path does not exist: {p}")

    roots = allowed_roots()
    if not roots:
        raise ValueError("No allowed roots configured. Set LOCAL_AI_ALLOWED_ROOTS.")
    if not any(str(p).startswith(str(root)) for root in roots):
        raise ValueError(
            f"Path is outside allowed roots: {p}\nAllowed roots: {', '.join(str(r) for r in roots)}"
        )
    return p


def run(cmd: list[str], cwd: Path, timeout: int = 300) -> str:
    p = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return f"$ {' '.join(cmd)}\n(exit {p.returncode})\n{p.stdout}"


@mcp.tool()
def local_ai_status() -> str:
    """Check whether the local MLX model servers appear reachable."""
    hosts = {
        "orchestrator": os.environ.get("ORCH_BASE_URL", "http://127.0.0.1:8001/v1"),
        "developer": os.environ.get("DEV_BASE_URL", "http://10.10.10.2:8002/v1"),
        "reviewer": os.environ.get("REVIEW_BASE_URL", "http://10.10.10.2:8003/v1"),
    }
    lines: list[str] = []
    for name, base_url in hosts.items():
        url = base_url.rstrip("/") + "/models"
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                lines.append(f"{name}: OK {url} HTTP {r.status}")
        except Exception as e:
            lines.append(f"{name}: FAIL {url} {type(e).__name__}: {e}")
    return "\n".join(lines)


@mcp.tool()
def git_local_summary(workspace: str = ".") -> str:
    """Show git status and diff stat for a local workspace."""
    ws = resolve_allowed(workspace)
    parts = [run(["git", "status", "--short"], ws, timeout=60), run(["git", "diff", "--stat"], ws, timeout=60)]
    return "\n\n".join(parts)[-20000:]


@mcp.tool()
def run_local_plan(plan_file: str, workspace: str = ".", in_place: bool = False, timeout_minutes: int = 60) -> str:
    """
    Execute a frontier-generated plan using the local multi-agent system.

    plan_file: path to the markdown plan file.
    workspace: repo/worktree path. Use an absolute path for best reliability.
    in_place: false means create a separate git worktree; true edits current workspace.
    timeout_minutes: max runtime for this tool call.
    """
    ws = resolve_allowed(workspace)
    plan = resolve_allowed(plan_file)

    local_exec = os.environ.get("LOCAL_EXEC_PLAN_BIN", str(Path.home() / "ai" / "local-ai-stack" / ".venv" / "bin" / "local-exec-plan"))
    if not Path(local_exec).exists():
        local_exec = str(Path.home() / "ai" / "bin" / "local-exec-plan")

    cmd = [local_exec, str(plan), "--workspace", str(ws)]
    if in_place:
        cmd.append("--in-place")

    try:
        p = subprocess.run(
            cmd,
            cwd=str(ws),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=max(60, timeout_minutes * 60),
        )
        output = p.stdout
        return f"Command: {' '.join(cmd)}\nExit code: {p.returncode}\n\n{output[-30000:]}"
    except subprocess.TimeoutExpired as e:
        output = e.stdout or ""
        return f"TIMEOUT after {timeout_minutes} minutes.\nPartial output:\n{output[-20000:]}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
