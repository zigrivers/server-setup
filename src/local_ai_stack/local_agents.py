#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph
from openai import OpenAI
from rich import print


# Load .env from current working directory or parent repo root.
load_dotenv()


class AgentState(TypedDict, total=False):
    task: str
    workspace: str
    plan: str
    developer_output: str
    review_output: str
    test_output: str
    approved: bool
    iteration: int
    history: list[str]


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}. Check your .env file.")
    return value


def make_client(base_url: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=os.getenv("LOCAL_API_KEY", "not-needed"))


# ---------------------------------------------------------------------
# Required configuration
# ---------------------------------------------------------------------
# IMPORTANT:
# mlx_lm.server does NOT understand model='local' unless you build your
# own aliasing layer. It treats the model field as a real local path or
# Hugging Face repo ID. If you send "local", it tries to resolve:
#   https://huggingface.co/local
# and returns a Repository Not Found / 404 error.
# ---------------------------------------------------------------------

ORCH_BASE_URL = required_env("ORCH_BASE_URL")
DEV_BASE_URL = required_env("DEV_BASE_URL")
REVIEW_BASE_URL = required_env("REVIEW_BASE_URL")

ORCH_MODEL = required_env("ORCH_MODEL")
DEV_MODEL = required_env("DEV_MODEL")
REVIEW_MODEL = required_env("REVIEW_MODEL")

for env_name, model_name in {
    "ORCH_MODEL": ORCH_MODEL,
    "DEV_MODEL": DEV_MODEL,
    "REVIEW_MODEL": REVIEW_MODEL,
}.items():
    if model_name in {"local", "default"}:
        raise RuntimeError(
            f"{env_name}={model_name!r} will not work with mlx_lm.server. "
            "Use the full model path on the hosting Mac instead."
        )

MAX_REVIEW_LOOPS = int(os.getenv("MAX_REVIEW_LOOPS", "3"))
ALLOW_UNSAFE_TOOLS = os.getenv("ALLOW_UNSAFE_TOOLS", "0") == "1"

ORCH = make_client(ORCH_BASE_URL)
DEV = make_client(DEV_BASE_URL)
REVIEW = make_client(REVIEW_BASE_URL)


def extract_message_text(message: Any) -> str:
    """Extract assistant output from OpenAI-compatible responses."""
    content = getattr(message, "content", None)
    if content:
        return content

    reasoning = getattr(message, "reasoning", None)
    if reasoning:
        return reasoning

    if isinstance(message, dict):
        return message.get("content") or message.get("reasoning") or ""

    return ""


def chat(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.4,
    max_tokens: int = 4096,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    system.strip()
                    + "\n\nAnswer with the requested output only. "
                    "Do not include hidden reasoning, thinking traces, or analysis."
                ),
            },
            {"role": "user", "content": user.strip()},
        ],
        temperature=temperature,
        top_p=0.95,
        max_tokens=max_tokens,
    )

    message = response.choices[0].message
    text = extract_message_text(message)
    if not text.strip():
        raise RuntimeError(
            "Model returned an empty assistant message. Check server response, model path, "
            "and whether the model is returning reasoning-only output."
        )
    return text


def run_cmd(cmd: str, cwd: Path, timeout: int = 180) -> str:
    blocked_fragments = [
        "sudo ",
        " rm -rf /",
        " rm -rf ~",
        "mkfs",
        "diskutil erase",
        ":(){",
        "chmod -R 777 /",
        "> /dev/sd",
        "shutdown",
        "reboot",
    ]

    if not ALLOW_UNSAFE_TOOLS:
        if any(fragment in f" {cmd} " for fragment in blocked_fragments):
            return f"[BLOCKED unsafe command]\n{cmd}"
        if ".." in cmd or "~/" in cmd:
            return f"[BLOCKED path escape]\n{cmd}"

    try:
        p = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return f"$ {cmd}\n(exit {p.returncode})\n{p.stdout[-12000:]}"
    except subprocess.TimeoutExpired:
        return f"$ {cmd}\n[TIMEOUT after {timeout}s]"


def ensure_workspace(path: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(path))
    workspace = Path(expanded).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    if not (workspace / ".git").exists():
        run_cmd("git init", workspace)
        run_cmd('git config user.email "local-agent@example.local"', workspace)
        run_cmd('git config user.name "Local AI Agent"', workspace)

    return workspace


def memory_path(workspace: Path) -> Path:
    return workspace / ".agent_memory.jsonl"


def append_memory(workspace: Path, event: dict[str, Any]) -> None:
    event = dict(event)
    event["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with memory_path(workspace).open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def recent_memory(workspace: Path, limit: int = 12) -> str:
    path = memory_path(workspace)
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return "\n".join(lines)


def repo_tree(workspace: Path, max_files: int = 200) -> str:
    ignore = {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }

    files: list[str] = []
    for p in workspace.rglob("*"):
        rel = p.relative_to(workspace)
        if any(part in ignore for part in rel.parts):
            continue
        if p.is_file():
            files.append(str(rel))
        if len(files) >= max_files:
            break

    return "\n".join(sorted(files)) or "(empty workspace)"


def git_diff(workspace: Path) -> str:
    return run_cmd("git diff -- .", workspace, timeout=60)


def git_status(workspace: Path) -> str:
    return run_cmd("git status --short", workspace, timeout=60)


def extract_tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.S | re.I)
    return m.group(1).strip() if m else ""


def extract_commands(text: str) -> list[str]:
    raw = extract_tag(text, "commands")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    return []


def apply_patch(patch: str, workspace: Path) -> str:
    if not patch.strip():
        return "[no patch supplied]"

    p = subprocess.run(
        ["git", "apply", "--whitespace=fix", "-"],
        input=patch,
        text=True,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if p.returncode == 0:
        return "[patch applied with git apply]"

    p2 = subprocess.run(
        ["patch", "-p1"],
        input=patch,
        text=True,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if p2.returncode == 0:
        return "[patch applied with patch -p1]"

    return "[patch failed]\n--- git apply ---\n" + p.stdout + "\n--- patch -p1 ---\n" + p2.stdout


def auto_tests(workspace: Path) -> list[str]:
    commands: list[str] = []
    if (workspace / "pyproject.toml").exists() or (workspace / "pytest.ini").exists() or (workspace / "tests").exists():
        commands.append("python -m pytest -q")
    if (workspace / "package.json").exists():
        commands.append("npm test")
    if (workspace / "Cargo.toml").exists():
        commands.append("cargo test")
    if (workspace / "go.mod").exists():
        commands.append("go test ./...")
    return commands


def orchestrate(state: AgentState) -> AgentState:
    workspace = ensure_workspace(state["workspace"])
    memory = recent_memory(workspace)

    system = """
You are the AI Agent Orchestrator.
You plan tasks, define acceptance criteria, and delegate implementation to a developer agent.
Be decisive. Produce an actionable plan, not a motivational essay.
"""

    user = f"""
Task:
{state["task"]}

Workspace:
{workspace}

Repo tree:
{repo_tree(workspace)}

Recent memory:
{memory or "(none)"}

Return:
1. Goal
2. Constraints
3. Files likely to change
4. Implementation plan
5. Review checklist
"""

    plan = chat(ORCH, ORCH_MODEL, system, user, temperature=0.35, max_tokens=4096)
    append_memory(workspace, {"type": "plan", "content": plan})

    print("\n[bold cyan]ORCHESTRATOR PLAN[/bold cyan]\n")
    print(plan)

    return {
        **state,
        "plan": plan,
        "iteration": 0,
        "approved": False,
        "history": state.get("history", []) + ["orchestrator_plan"],
    }


def develop(state: AgentState) -> AgentState:
    workspace = ensure_workspace(state["workspace"])
    iteration = int(state.get("iteration", 0)) + 1
    review = state.get("review_output", "")
    diff_before = git_diff(workspace)

    system = """
You are the AI Agent Developer.
You write correct, maintainable code. You respond with a unified diff patch and commands to run.
Do not edit outside the workspace. Prefer small, reviewable changes.

Required output format:

<summary>
Brief summary of what you changed.
</summary>

<patch>
Unified diff here. Use git-compatible diff format.
</patch>

<commands>
["python -m pytest -q"]
</commands>

If no tests exist, create tests where appropriate.
"""

    user = f"""
Task:
{state["task"]}

Orchestrator plan:
{state["plan"]}

Current repo tree:
{repo_tree(workspace)}

Current git status:
{git_status(workspace)}

Current diff before your work:
{diff_before[-12000:]}

Reviewer feedback from previous pass:
{review or "(none)"}

Iteration:
{iteration}

Produce a patch and commands.
"""

    dev_output = chat(DEV, DEV_MODEL, system, user, temperature=0.45, max_tokens=12000)
    patch = extract_tag(dev_output, "patch")
    commands = extract_commands(dev_output)

    patch_result = apply_patch(patch, workspace)

    command_logs: list[str] = [patch_result]
    for cmd in commands:
        command_logs.append(run_cmd(cmd, workspace, timeout=300))

    if not commands:
        for cmd in auto_tests(workspace):
            command_logs.append(run_cmd(cmd, workspace, timeout=300))

    test_output = "\n\n".join(command_logs)
    append_memory(
        workspace,
        {
            "type": "developer_iteration",
            "iteration": iteration,
            "summary": extract_tag(dev_output, "summary"),
            "test_output_tail": test_output[-4000:],
        },
    )

    print(f"\n[bold green]DEVELOPER ITERATION {iteration}[/bold green]\n")
    print(extract_tag(dev_output, "summary") or dev_output[:2000])
    print("\n[bold]Tool/test output tail:[/bold]")
    print(test_output[-4000:])

    return {
        **state,
        "developer_output": dev_output,
        "test_output": test_output,
        "iteration": iteration,
        "history": state.get("history", []) + [f"developer_{iteration}"],
    }


def review(state: AgentState) -> AgentState:
    workspace = ensure_workspace(state["workspace"])
    diff = git_diff(workspace)
    status = git_status(workspace)

    system = """
You are the AI Agent Code Reviewer.
You review for correctness, security, maintainability, performance, tests, and hidden edge cases.
Be strict. Do not approve unless the patch is actually acceptable.

Return valid JSON only:
{
  "approved": true or false,
  "summary": "...",
  "blocking_issues": ["..."],
  "non_blocking_suggestions": ["..."],
  "required_changes": ["..."]
}
"""

    user = f"""
Task:
{state["task"]}

Orchestrator plan:
{state["plan"]}

Developer output:
{state.get("developer_output", "")[-12000:]}

Git status:
{status}

Diff to review:
{diff[-30000:]}

Test/tool output:
{state.get("test_output", "")[-12000:]}

Review this patch.
"""

    raw = chat(REVIEW, REVIEW_MODEL, system, user, temperature=0.2, max_tokens=6000)

    approved = False
    try:
        data = json.loads(raw)
        approved = bool(data.get("approved"))
    except Exception:
        approved = '"approved": true' in raw.lower() or "approved: true" in raw.lower()

    append_memory(
        workspace,
        {
            "type": "review",
            "iteration": state.get("iteration", 0),
            "approved": approved,
            "content": raw,
        },
    )

    print("\n[bold magenta]REVIEW[/bold magenta]\n")
    print(raw)

    return {
        **state,
        "review_output": raw,
        "approved": approved,
        "history": state.get("history", []) + [f"review_{state.get('iteration', 0)}"],
    }


def route_after_review(state: AgentState) -> str:
    if state.get("approved"):
        return "end"
    if int(state.get("iteration", 0)) >= MAX_REVIEW_LOOPS:
        return "end"
    return "develop"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("orchestrate", orchestrate)
    graph.add_node("develop", develop)
    graph.add_node("review", review)
    graph.set_entry_point("orchestrate")
    graph.add_edge("orchestrate", "develop")
    graph.add_edge("develop", "review")
    graph.add_conditional_edges("review", route_after_review, {"develop": "develop", "end": END})
    return graph.compile()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="+", help="Task for the local multi-agent system")
    parser.add_argument(
        "--workspace",
        default=os.getenv("WORKSPACE", "~/ai/workspaces/default_project"),
        help="Workspace directory",
    )
    args = parser.parse_args()

    task = " ".join(args.task)
    workspace = str(Path(os.path.expandvars(os.path.expanduser(args.workspace))).resolve())

    print("\n[bold blue]LOCAL AGENT CONFIG[/bold blue]")
    print(f"Orchestrator endpoint: {ORCH_BASE_URL}")
    print(f"Developer endpoint:    {DEV_BASE_URL}")
    print(f"Reviewer endpoint:     {REVIEW_BASE_URL}")
    print(f"Orchestrator model:    {ORCH_MODEL}")
    print(f"Developer model:       {DEV_MODEL}")
    print(f"Reviewer model:        {REVIEW_MODEL}")
    print(f"Workspace:             {workspace}")
    print(f"Max review loops:      {MAX_REVIEW_LOOPS}")
    print(f"Unsafe tools allowed:  {ALLOW_UNSAFE_TOOLS}")

    app = build_graph()
    final = app.invoke({"task": task, "workspace": workspace, "history": []}, config={"recursion_limit": 20})

    print("\n[bold yellow]FINAL STATE[/bold yellow]")
    print(f"Approved: {final.get('approved')}")
    print(f"Iterations: {final.get('iteration')}")
    print(f"Workspace: {workspace}")

    if not final.get("approved"):
        print("\n[bold red]Stopped without approval. Read reviewer feedback above.[/bold red]")


if __name__ == "__main__":
    main()
