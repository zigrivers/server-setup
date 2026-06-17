from __future__ import annotations

import json
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
            Path.home() / "Documents" / "dev-projects",
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


REVIEW_SYSTEM_PROMPT = """You are a strict senior code reviewer. You receive a git status \
and a unified diff. Review ONLY what the diff shows; do not invent context.

Respond in exactly this structure:
## Blocking issues
(numbered list, or "None")
## Non-blocking suggestions
(numbered list, or "None")
## Verdict
One line: SAFE TO MERGE or NEEDS CHANGES, plus a one-sentence reason.

Be concrete: cite file names and hunks from the diff. Check for: logic errors, \
shell-safety problems, hardcoded paths or secrets, broken error handling, and \
mismatches between code and comments/docs."""

DIFF_SCOPES = {
    "uncommitted": ["git", "diff", "HEAD"],
    "staged": ["git", "diff", "--cached"],
    "since-main": ["git", "diff", "main...HEAD"],
}
MAX_DIFF_CHARS = 60_000


def _truncate_middle(text: str, limit: int = MAX_DIFF_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n\n[... diff truncated for length ...]\n\n" + text[-half:]


def _collect_diff(ws: Path, scope: str) -> str:
    if scope not in DIFF_SCOPES:
        raise ValueError(f"Unknown scope: {scope!r}. Choose from {sorted(DIFF_SCOPES)}")
    p = subprocess.run(
        DIFF_SCOPES[scope],
        cwd=str(ws),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    if p.returncode != 0:
        raise ValueError(f"git diff failed (exit {p.returncode}):\n{p.stdout[-2000:]}")
    return _truncate_middle(p.stdout)


def _review_model(base_url: str, timeout: int = 10) -> str:
    url = base_url.rstrip("/") + "/models"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    models = data.get("data") or []
    if not models:
        raise ValueError(f"Reviewer endpoint serves no models: {url}")
    return models[0]["id"]


def _post_json(url: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _review_base_url() -> str:
    """Endpoint local_review generates against.

    Defaults to the orchestrator (ORCH_BASE_URL — a fast MoE on localhost),
    NOT the dense reviewer model on 8003, which generates at ~10 tok/s and blows
    the request timeout on any substantive review. Override with
    LOCAL_REVIEW_BASE_URL to force a specific endpoint (e.g. the 8003 reviewer).
    """
    return (
        os.environ.get("LOCAL_REVIEW_BASE_URL")
        or os.environ.get("ORCH_BASE_URL")
        or "http://127.0.0.1:8001/v1"
    )


def _review_max_tokens() -> int:
    """Output-token cap for a review (LOCAL_REVIEW_MAX_TOKENS, default 3000).

    Bounds generation time: at the orchestrator's ~34 tok/s, 3000 tokens is
    ~90s — well under the request timeout — while still fitting a thorough
    structured review without truncation.
    """
    try:
        return max(256, int(os.environ.get("LOCAL_REVIEW_MAX_TOKENS", "3000")))
    except ValueError:
        return 3000


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
def local_review(workspace: str = ".", scope: str = "uncommitted", instructions: str = "", timeout_seconds: int = 600) -> str:
    """
    Send the workspace's git diff to a local model for a real code review.

    workspace: repo path (resolved against allowed roots).
    scope: 'uncommitted' (working tree vs HEAD), 'staged', or 'since-main'.
    instructions: optional extra focus areas for the reviewer.
    timeout_seconds: max time to wait for the model.

    Targets LOCAL_REVIEW_BASE_URL or the orchestrator (ORCH_BASE_URL) by
    default — the dense reviewer on 8003 is too slow for interactive use.
    """
    ws = resolve_allowed(workspace)
    diff = _collect_diff(ws, scope)
    if not diff.strip():
        return f"No changes found for scope '{scope}' in {ws} — nothing to review."

    status = run(["git", "status", "--short"], ws, timeout=60)
    base_url = _review_base_url()
    model = _review_model(base_url)

    user_parts = []
    if instructions:
        user_parts.append(f"Caller-requested review focus: {instructions}")
    user_parts.append(f"git status:\n{status}")
    user_parts.append(f"Unified diff (scope: {scope}):\n```diff\n{diff}\n```")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        "temperature": 0.1,
        "max_tokens": _review_max_tokens(),
        # Disable the model's hidden reasoning channel. The orchestrator is a
        # thinking model that otherwise spends the whole token budget in a
        # `reasoning` field and emits no `content` (finish_reason=length). This
        # kwarg makes it answer directly — faster, and the review lands in
        # `content` where we can read it.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        data = _post_json(base_url.rstrip("/") + "/chat/completions", payload, timeout=max(30, timeout_seconds))
    except (TimeoutError, OSError) as e:
        return (
            f"Local review timed out or failed against {base_url} "
            f"({type(e).__name__}: {e}). The model may be generating too slowly. "
            f"Try a smaller scope, lower LOCAL_REVIEW_MAX_TOKENS, raise timeout_seconds, "
            f"or point LOCAL_REVIEW_BASE_URL at a faster endpoint."
        )
    choice = data["choices"][0]
    text = (choice.get("message", {}).get("content") or "").strip()
    if not text:
        fr = choice.get("finish_reason")
        return (
            f"Local review produced no answer from {model} via {base_url} "
            f"(finish_reason={fr}). The model likely hit the token cap before "
            f"answering — raise LOCAL_REVIEW_MAX_TOKENS or timeout_seconds."
        )
    footer = f"Reviewer: {model} via {base_url} (scope: {scope})"
    if choice.get("finish_reason") == "length":
        footer += " [truncated at max_tokens — raise LOCAL_REVIEW_MAX_TOKENS for a longer review]"
    return f"{text}\n\n---\n{footer}"


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
