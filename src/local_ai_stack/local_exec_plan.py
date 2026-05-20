#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def run(cmd: list[str], cwd: Path, check: bool = True) -> str:
    print("+ " + " ".join(cmd), file=sys.stderr)
    p = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and p.returncode != 0:
        print(p.stdout, file=sys.stderr)
        raise SystemExit(p.returncode)
    return p.stdout.strip()


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:60] or "local-ai-task"


def git_root(path: Path) -> Path:
    out = run(["git", "rev-parse", "--show-toplevel"], path)
    return Path(out).resolve()


def load_local_agents(controller_path: Path):
    controller_dir = controller_path.parent
    os.chdir(controller_dir)
    sys.path.insert(0, str(controller_dir))

    spec = importlib.util.spec_from_file_location("local_agents", controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {controller_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_controller_path() -> Path:
    # Repo layout: scripts/local_exec_plan.py or installed package.
    # Prefer explicit LOCAL_AI_CONTROLLER; otherwise use package-adjacent local_agents.py.
    if os.environ.get("LOCAL_AI_CONTROLLER"):
        return Path(os.environ["LOCAL_AI_CONTROLLER"]).expanduser().resolve()
    return Path(__file__).with_name("local_agents.py").resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a frontier-generated plan using the local multi-agent system.")
    parser.add_argument("plan_file", help="Path to plans/YYYY-MM-DD-feature.md")
    parser.add_argument("--workspace", default=".", help="Repo or worktree path")
    parser.add_argument("--branch", default="", help="Branch name for the local AI worktree")
    parser.add_argument("--worktree-path", default="", help="Explicit worktree path")
    parser.add_argument("--in-place", action="store_true", help="Run in current worktree instead of creating a new worktree")
    args = parser.parse_args()

    plan_path = Path(args.plan_file).expanduser().resolve()
    if not plan_path.exists():
        raise SystemExit(f"Plan file not found: {plan_path}")

    plan_text = plan_path.read_text(encoding="utf-8")
    base_root = git_root(Path(args.workspace).expanduser().resolve())

    status = run(["git", "status", "--porcelain"], base_root)
    if status and not args.in_place:
        print(
            "[warning] Base worktree has uncommitted changes. The new worktree will be based on committed HEAD.",
            file=sys.stderr,
        )

    feature_slug = slugify(plan_path.stem)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    branch = args.branch or f"ai/local/{feature_slug}-{timestamp}"

    if args.in_place:
        worktree = base_root
    else:
        worktree = Path(args.worktree_path).expanduser().resolve() if args.worktree_path else base_root.parent / f"{base_root.name}-local-{feature_slug}-{timestamp}"
        run(["git", "worktree", "add", "-b", branch, str(worktree)], base_root)

    local_dir = worktree / ".local-ai"
    local_dir.mkdir(parents=True, exist_ok=True)

    task_file = local_dir / "task.md"
    task_file.write_text(
        f"""# Local AI execution task

You are executing a frontier-model implementation plan.

## Operating rules

- Implement the plan as written.
- Prefer small, reviewable changes.
- Add or update tests.
- Run relevant tests, lint, and type checks.
- Do not touch secrets or unrelated files.
- Do not change deployment infrastructure unless the plan explicitly asks for it.
- Stop after local reviewer approval or after the configured review-loop limit.

## Plan source

{plan_path}

## Plan

{plan_text}
""",
        encoding="utf-8",
    )

    controller_path = default_controller_path()
    if not controller_path.exists():
        raise SystemExit(f"Local agent controller not found: {controller_path}")

    print(f"\nWorkspace: {worktree}")
    print(f"Branch:    {branch if not args.in_place else '(current branch)'}")
    print(f"Task file: {task_file}\n")

    local_agents = load_local_agents(controller_path)
    app = local_agents.build_graph()

    final = app.invoke(
        {"task": task_file.read_text(encoding="utf-8"), "workspace": str(worktree), "history": []},
        config={"recursion_limit": 20},
    )

    approved = bool(final.get("approved"))
    iterations = final.get("iteration")

    print("\n=== LOCAL AI EXECUTION COMPLETE ===")
    print(f"Approved:   {approved}")
    print(f"Iterations: {iterations}")
    print(f"Workspace:  {worktree}")

    if not approved:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
