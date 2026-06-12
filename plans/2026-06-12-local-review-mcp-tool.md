# `local_review` MCP Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `local_review` tool to the `local-ai-delegate` MCP server that sends a workspace's git diff to the local Reviewer model (port 8003) for a genuine model review — giving Claude, Codex, and Antigravity real multi-model reviews through the existing bridge — and update the docs/skills/Codex instructions to match.

**Architecture:** One new `@mcp.tool()` in `mcp/local_delegate_mcp/server.py`, built from three small testable helpers, matching the file's existing standalone style (stdlib `urllib` + `subprocess`, no `openai`/`httpx` imports, allowed-roots confinement). The reviewer's model id is discovered at call time from `GET {REVIEW_BASE_URL}/models` (the MCP env has no `REVIEW_MODEL`, and mlx_lm.server serves exactly one model). The Claude `local-review` skill is rewired to call the new tool instead of presenting `git diff --stat` as a "review."

**Tech Stack:** Python 3.12 stdlib + FastMCP (existing), pytest (already in the `dev` extra), bash installers (existing).

---

## Non-goals

- No multi-vote review across developer+reviewer models (single reviewer first; add later only if its reviews prove useful).
- No `~/.codex/prompts/` custom prompt (deliberately skipped — thin wrapper, add later if a real need shows up).
- No changes to the mlx servers, launchd, registrations (`server.py`'s path and env are unchanged, so no re-registration needed).
- No auth on the MCP server (unchanged threat model, see docs/SECURITY.md).

## Current system summary

- `mcp/local_delegate_mcp/server.py` exposes 3 tools: `local_ai_status` (endpoint ping), `git_local_summary` (git status + diff stat only — **no model involved**), `run_local_plan` (full pipeline). Nothing sends a diff to the Reviewer.
- MCP env (set by `scripts/register-mcp-{claude,codex}.sh`): `ORCH/DEV/REVIEW_BASE_URL`, `LOCAL_AI_ALLOWED_ROOTS`, `LOCAL_AI_DEFAULT_WORKSPACE`, `LOCAL_EXEC_PLAN_BIN`. **No model names.**
- `skills/claude/local-review/SKILL.md` claims to give "local findings" but only calls `git_local_summary`.
- `~/.codex/AGENTS.md` exists and is empty (0 bytes). Repo `AGENTS.md` documents endpoints but no review recipe.
- Repo has **no `tests/` directory**; `pytest` is declared in the `dev` and `all` extras but not installed in `.venv`.
- `docs/MCP.md` is the canonical tool reference ("It exposes three tools", sections per tool, prefixed-name list at lines 99–101, security bullet at line 140).

## Proposed architecture (after)

- `server.py` exposes 4 tools; `local_review(workspace, scope, instructions, timeout_seconds)` collects the diff (`uncommitted` | `staged` | `since-main`), truncates middle-out at 60 KB, discovers the reviewer model id, POSTs one chat completion, returns the review text + a footer naming model/endpoint.
- `tests/test_local_delegate_server.py` unit-tests the pure helpers (no network).
- `local-review` skill calls `local-ai-delegate__local_review` and layers frontier judgment on top.
- `~/.codex/AGENTS.md` (machine-local) carries a short "local AI stack" section telling Codex when to use the tool; the canonical copy of that snippet lives in `docs/MCP.md` so the repo stays the source of truth.

## Files expected to change

| File | Change |
|---|---|
| `mcp/local_delegate_mcp/server.py` | add `json` import, 4 helpers + `REVIEW_SYSTEM_PROMPT`, new `local_review` tool |
| `tests/test_local_delegate_server.py` | new — unit tests for helpers |
| `docs/MCP.md` | "three tools" → four; new tool section; prefixed-name list; security bullet; Codex AGENTS.md snippet |
| `skills/claude/local-review/SKILL.md` | call the real tool |
| `docs/html/local_ai_workflow_guide.html`, `docs/html/local_ai_infrastructure_overview.html`, `docs/html/antigravity_cli_workflow_guide.html` | add `local_review` beside existing `run_local_plan` mentions in tool lists |
| `~/.codex/AGENTS.md` | machine-local, not committed — write the snippet |
| `~/.claude/skills/`, `~/.gemini/antigravity-cli/skills/` | refreshed via existing installers |

---

### Task 1: Install pytest and write the failing tests

**Files:**
- Create: `tests/test_local_delegate_server.py`

- [ ] **Step 1: Install the dev extra into the venv**

```bash
cd ~/Developer/server-setup
uv pip install -e '.[dev]' --python .venv/bin/python
.venv/bin/pytest --version
```

Expected: pytest 8.x prints.

- [ ] **Step 2: Write the failing tests.** Create `tests/test_local_delegate_server.py`:

```python
"""Unit tests for mcp/local_delegate_mcp/server.py helpers (no network)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The repo's mcp/ directory would shadow the installed `mcp` package if the
# repo root were on sys.path (namespace-package resolution). Strip it before
# loading the server module, which does `from mcp.server.fastmcp import FastMCP`.
sys.path = [p for p in sys.path if Path(p or ".").resolve() != ROOT]

_spec = importlib.util.spec_from_file_location(
    "local_delegate_server", ROOT / "mcp" / "local_delegate_mcp" / "server.py"
)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env={**env, "PATH": "/usr/bin:/bin"})
    git("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "init")
    monkeypatch.setenv("LOCAL_AI_ALLOWED_ROOTS", str(tmp_path))
    return repo


def test_truncate_middle_short_text_unchanged():
    assert server._truncate_middle("abc", limit=10) == "abc"


def test_truncate_middle_long_text_keeps_head_and_tail():
    text = "H" * 50 + "T" * 50
    out = server._truncate_middle(text, limit=40)
    assert len(out) < len(text)
    assert out.startswith("H" * 20)
    assert out.endswith("T" * 20)
    assert "truncated" in out


def test_collect_diff_uncommitted_change(git_repo):
    (git_repo / "a.txt").write_text("two\n")
    diff = server._collect_diff(git_repo, "uncommitted")
    assert "-one" in diff and "+two" in diff


def test_collect_diff_clean_tree_is_empty(git_repo):
    assert server._collect_diff(git_repo, "uncommitted").strip() == ""


def test_collect_diff_staged_scope(git_repo):
    (git_repo / "a.txt").write_text("two\n")
    subprocess.run(["git", "add", "a.txt"], cwd=git_repo, check=True, capture_output=True)
    assert "+two" in server._collect_diff(git_repo, "staged")


def test_collect_diff_unknown_scope_raises(git_repo):
    with pytest.raises(ValueError, match="Unknown scope"):
        server._collect_diff(git_repo, "nonsense")


def test_local_review_clean_tree_short_circuits_without_network(git_repo, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network must not be touched for an empty diff")
    monkeypatch.setattr(server, "_review_model", boom)
    out = server.local_review(workspace=str(git_repo))
    assert "nothing to review" in out.lower()


def test_local_review_outside_allowed_roots_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_ALLOWED_ROOTS", str(tmp_path / "only-this"))
    (tmp_path / "only-this").mkdir()
    with pytest.raises(ValueError, match="outside allowed roots"):
        server.local_review(workspace="/private/etc")
```

- [ ] **Step 3: Run tests to verify they fail for the right reason**

```bash
cd ~/Developer/server-setup
.venv/bin/pytest tests/ -v 2>&1 | tail -15
```

Expected: collection-time or attribute errors like `module 'local_delegate_server' has no attribute '_truncate_middle'` — NOT import errors about FastMCP (if you see a FastMCP/mcp import error, the sys.path shadow-strip in the test header isn't working; fix that first).

Note on `local_review` being decorated: with FastMCP, `@mcp.tool()` returns the original function (registration is by side effect), so `server.local_review(...)` stays directly callable. If that assumption fails at test time (TypeError: 'Tool' object is not callable), restructure in Task 2: implement `def _local_review_impl(...)` with the logic, register a thin `@mcp.tool()` wrapper calling it, and point the two `local_review` tests at `server._local_review_impl`.

### Task 2: Implement the helpers and the tool

**Files:**
- Modify: `mcp/local_delegate_mcp/server.py`

- [ ] **Step 1: Add `json` to the imports** (line 3 area):

```python
import json
import os
import subprocess
import urllib.request
from pathlib import Path
```

- [ ] **Step 2: Add the constants and helpers** after the existing `run()` helper (after line 60):

```python
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
```

- [ ] **Step 3: Add the tool** after `git_local_summary` (keep `run_local_plan` last so the file reads light-to-heavy):

```python
@mcp.tool()
def local_review(workspace: str = ".", scope: str = "uncommitted", instructions: str = "", timeout_seconds: int = 300) -> str:
    """
    Send the workspace's git diff to the local Reviewer model for a real code review.

    workspace: repo path (resolved against allowed roots).
    scope: 'uncommitted' (working tree vs HEAD), 'staged', or 'since-main'.
    instructions: optional extra focus areas for the reviewer.
    timeout_seconds: max time to wait for the reviewer model.
    """
    ws = resolve_allowed(workspace)
    diff = _collect_diff(ws, scope)
    if not diff.strip():
        return f"No changes found for scope '{scope}' in {ws} — nothing to review."

    status = run(["git", "status", "--short"], ws, timeout=60)
    base_url = os.environ.get("REVIEW_BASE_URL", "http://10.10.10.2:8003/v1")
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
        "max_tokens": 2000,
    }
    data = _post_json(base_url.rstrip("/") + "/chat/completions", payload, timeout=max(30, timeout_seconds))
    text = data["choices"][0]["message"]["content"]
    return f"{text}\n\n---\nReviewer: {model} via {base_url} (scope: {scope})"
```

- [ ] **Step 4: Run the tests**

```bash
cd ~/Developer/server-setup
.venv/bin/pytest tests/ -v
```

Expected: all 8 tests PASS. (If the two `local_review` tests fail with a not-callable error, apply the `_local_review_impl` restructure described in Task 1 Step 3 and re-run.)

- [ ] **Step 5: Lint**

```bash
cd ~/Developer/server-setup
.venv/bin/ruff check mcp/ tests/
```

Expected: no errors (ruff is in the dev extra; config in pyproject.toml).

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/server-setup
git add mcp/local_delegate_mcp/server.py tests/test_local_delegate_server.py
git commit -m "feat: add local_review MCP tool — real diff review by the local Reviewer model"
```

End the commit message with a blank line then: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

### Task 3: Live end-to-end check against the real Reviewer

- [ ] **Step 1: Make a scratch repo with a deliberate bug and review it**

```bash
mkdir -p ~/ai/workspaces/local-review-test-0612 && cd ~/ai/workspaces/local-review-test-0612
git init -q -b main 2>/dev/null || git init -q
cat > deploy.sh <<'EOF'
#!/bin/bash
rm -rf $TARGET_DIR/*
cp -r build/ $TARGET_DIR/
EOF
git add deploy.sh && git commit -q -m "add deploy script"
printf '#!/bin/bash\nrm -rf $TARGET_DIR/*\ncp -r build/ $TARGET_DIR/\necho done\n' > deploy.sh
```

- [ ] **Step 2: Call the tool function directly under the venv** (same import path as the tests; this hits the real 8003 endpoint)

```bash
cd ~/Developer/server-setup
.venv/bin/python - <<'EOF'
import importlib.util, sys
from pathlib import Path
ROOT = Path.cwd()
sys.path = [p for p in sys.path if Path(p or ".").resolve() != ROOT]
spec = importlib.util.spec_from_file_location("s", ROOT / "mcp/local_delegate_mcp/server.py")
s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)
print(s.local_review(workspace=str(Path.home() / "ai/workspaces/local-review-test-0612")))
EOF
```

Expected: a structured review (Blocking issues / Non-blocking suggestions / Verdict) that plausibly flags the unquoted `$TARGET_DIR` with `rm -rf` (an unset var deletes from `/`), ending with a `Reviewer: <model id> via http://10.10.10.2:8003/v1` footer. The reviewer's exact findings may vary — the requirement is a real model response in the required structure, not specific findings. If it returns an HTTP/URL error, check `local_ai_status` first; do not proceed to Task 4 until this works.

### Task 4: Update docs/MCP.md

**Files:**
- Modify: `docs/MCP.md`

- [ ] **Step 1: Update the intro** (line 5): change "It exposes three tools over stdio." to "It exposes four tools over stdio."

- [ ] **Step 2: Insert a new tool section** between `git_local_summary` (ends line 30) and `run_local_plan` (starts line 32):

```markdown
### `local_review(workspace=".", scope="uncommitted", instructions="", timeout_seconds=300) -> str`

Sends the workspace's git diff to the local Reviewer model
(`REVIEW_BASE_URL`, port 8003) for a genuine code review and returns the
model's findings (Blocking issues / Non-blocking suggestions / Verdict).

- `scope`: `uncommitted` (working tree vs HEAD), `staged`, or `since-main`.
- `instructions`: optional focus areas passed to the reviewer.
- The model id is discovered at call time from `GET {REVIEW_BASE_URL}/models`,
  so no model name needs to be configured.
- Diffs are truncated middle-out at 60 KB; empty diffs return early without
  calling the model.

This is the cheap second-opinion tool — for executing a plan with the full
orchestrator/developer/reviewer loop, use `run_local_plan` instead.
```

- [ ] **Step 3: Update the prefixed-name list** (lines 99–101): add `local-ai-delegate__local_review` to the enumeration.

- [ ] **Step 4: Update the security bullet** (line 140): change "`git_local_summary` and `run_local_plan` are confined to" to "`git_local_summary`, `local_review`, and `run_local_plan` are confined to".

- [ ] **Step 5: Add the Codex AGENTS.md snippet** at the end of the "Registering with Codex" section (after line 122):

````markdown
### Recommended `~/.codex/AGENTS.md` section

So Codex reaches for the local stack unprompted, add this to the (global)
`~/.codex/AGENTS.md`:

```markdown
## Local AI stack (two-Mac, always running)

A local MLX stack is available via the `local-ai-delegate` MCP server:

- `local_review` — send the current git diff to the local Reviewer model
  for a second opinion. Use it before merging non-trivial changes, then
  state where you agree, disagree, and what it missed. Treat it as input,
  not a verdict.
- `run_local_plan` — execute an approved plan file with the local
  multi-agent loop (long-running).
- `local_ai_status` — check the endpoints if either tool errors.

The endpoints are OpenAI-compatible if direct calls are ever needed
(orchestrator 127.0.0.1:8001, developer 10.10.10.2:8002, reviewer
10.10.10.2:8003); the `model` field must be the exact id from
`GET /v1/models`, never an alias.
```
````

### Task 5: Rewire the local-review skill

**Files:**
- Modify: `skills/claude/local-review/SKILL.md`

- [ ] **Step 1: Replace the file's full contents with:**

```markdown
---
name: local-review
description: Use the local AI stack for a second opinion on the current git diff or project state
argument-hint: [optional file, area, or diff description]
allowed-tools: Read, Grep, Glob, Bash(git diff), Bash(git status), local-ai-delegate__local_review, local-ai-delegate__git_local_summary, local-ai-delegate__local_ai_status
---

Use the local AI stack as a second-opinion reviewer.

Process:

1. Identify the relevant workspace (absolute path).
2. Inspect git status and git diff yourself first.
3. Call `local-ai-delegate__local_review` with that workspace.
   - scope: `uncommitted` by default; `since-main` when reviewing a branch.
   - If the user gave a focus area in $ARGUMENTS, pass it as `instructions`.
   - If the tool errors, check `local-ai-delegate__local_ai_status` and report.
4. Present the local reviewer's findings verbatim (clearly attributed to the
   local Reviewer model).
5. Add your own frontier-level judgment:
   - what you agree with
   - what you disagree with
   - what was missed
   - whether this is safe to merge

Target: $ARGUMENTS
```

- [ ] **Step 2: Reinstall skills on both CLIs**

```bash
cd ~/Developer/server-setup
scripts/install-claude-skills.sh
scripts/install-antigravity-skills.sh
diff skills/claude/local-review/SKILL.md ~/.claude/skills/local-review/SKILL.md && echo CLAUDE-SYNCED
diff skills/claude/local-review/SKILL.md ~/.gemini/antigravity-cli/skills/local-review/SKILL.md && echo ANTIGRAVITY-SYNCED
```

Expected: both SYNCED markers.

### Task 6: Update the HTML workflow guides' tool lists

**Files:**
- Modify: `docs/html/local_ai_workflow_guide.html`, `docs/html/local_ai_infrastructure_overview.html`, `docs/html/antigravity_cli_workflow_guide.html`

- [ ] **Step 1: Locate each `run_local_plan` mention**

```bash
cd ~/Developer/server-setup
grep -n 'run_local_plan' docs/html/local_ai_workflow_guide.html docs/html/local_ai_infrastructure_overview.html docs/html/antigravity_cli_workflow_guide.html
```

- [ ] **Step 2:** Where the guides enumerate the MCP tools, add a `local_review` entry as a sibling using the SAME markup as the neighboring tool entries (same tags/classes), with this text: "`local_review` — sends the workspace's git diff to the Reviewer model (8003) for a genuine local code review." Where `run_local_plan` is mentioned in prose (not a tool list), leave it alone. After editing, validate:

```bash
.venv/bin/python -c "import html.parser; p=html.parser.HTMLParser(); [p.feed(open(f).read()) for f in ['docs/html/local_ai_workflow_guide.html','docs/html/local_ai_infrastructure_overview.html','docs/html/antigravity_cli_workflow_guide.html']]; print('parsed ok')"
```

- [ ] **Step 3: Commit and push docs + skill together**

```bash
cd ~/Developer/server-setup
git add docs/MCP.md skills/claude/local-review/SKILL.md docs/html/
git commit -m "docs: document local_review tool; rewire local-review skill to use it"
git push origin main
```

End the commit message with a blank line then: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

### Task 7: Write `~/.codex/AGENTS.md` (machine-local)

- [ ] **Step 1:** The file exists and is empty (verify: `wc -c ~/.codex/AGENTS.md` → 0; if non-zero, APPEND instead of overwrite and report what was there). Write the exact "## Local AI stack" snippet from Task 4 Step 5 into it.

- [ ] **Step 2: Verify**

```bash
grep -c 'local_review' ~/.codex/AGENTS.md
```

Expected: ≥1.

### Task 8: Sync runtime clones and verify end state

- [ ] **Step 1: Fast-forward the runtime clones** (server.py is not launchd-executed — no service restarts)

```bash
git -C ~/ai/local-ai-stack pull --ff-only
ssh -o ConnectTimeout=10 admin@10.10.10.2 'git -C ~/ai/local-ai-stack pull --ff-only'
```

- [ ] **Step 2: Full verification**

```bash
cd ~/Developer/server-setup
.venv/bin/pytest tests/ -q
scripts/preflight.sh
claude mcp list 2>&1 | grep local-ai-delegate
git status --short; git log origin/main..HEAD --oneline
```

Expected: tests pass, preflight PASS, MCP ✔ Connected, clean tree, nothing unpushed.

---

## Acceptance criteria

1. `.venv/bin/pytest tests/ -q` — 8/8 pass.
2. The Task 3 live call returns a structured review from the real Reviewer model with the model-id footer.
3. A **fresh** Claude Code session can call `local-ai-delegate__local_review` on a repo with uncommitted changes and get a model review (existing sessions keep the old server instance — restart required).
4. `codex` in a fresh session lists `local_review` among local-ai-delegate tools.
5. `docs/MCP.md` says "four tools" and documents `local_review`; the three HTML guides list it; the installed `local-review` skills on both CLIs reference `local-ai-delegate__local_review`.
6. `~/.codex/AGENTS.md` contains the local-stack section.
7. All checkouts (Developer, M1+M2 runtime clones) at the same pushed SHA.

## Test plan

- Unit: Task 1 tests (truncation, scope mapping, clean-tree short-circuit without network, allowed-roots rejection).
- Integration: Task 3 live review of a deliberately buggy shell script against the real 8003 endpoint.
- Regression: Task 8 preflight + MCP connection + existing-tool smoke (`local_ai_status` via `claude mcp list` health check).

## Rollback plan

- Code/docs/skill: `git revert <feat-sha> <docs-sha>` and push; `git -C ~/ai/local-ai-stack pull --ff-only` (both machines); re-run the two skill installers.
- `~/.codex/AGENTS.md`: truncate back to empty (`: > ~/.codex/AGENTS.md`).
- No registrations changed, so nothing to re-register.

## Docs updates

All in-plan (Tasks 4–6): `docs/MCP.md`, the three HTML guides, the skill. No other docs reference the tool count.

## Risks and edge cases

- **`@mcp.tool()` wrapper callability:** tests assume the decorated function stays directly callable. Mitigation is pre-planned (Task 1 Step 3 / Task 2 Step 4 restructure to `_local_review_impl`).
- **Repo `mcp/` dir shadows the installed `mcp` package** when repo root lands on `sys.path` (pytest). Handled by the shadow-strip header in the test file; if other tests are added later in a root `conftest.py`, keep the strip there instead.
- **Reviewer down / TB link down:** `_review_model` raises with the URL in the message; the skill's step 3 tells the caller to check `local_ai_status`. No retries by design — the caller decides.
- **Huge diffs:** 60 KB middle-out truncation keeps prompts inside the 27B model's context; the truncation marker tells the reviewer content was elided.
- **`since-main` scope on repos whose default branch isn't `main`:** `git diff main...HEAD` fails with a clear git error wrapped in ValueError. Acceptable for v1; revisit only if it bites.
- **Stale server instances:** running Claude/Codex sessions keep the old 3-tool server until restarted. Acceptance criterion 3 explicitly uses a fresh session.
- **Reviewer quality:** a 27B model may miss things or wave through bad diffs. The skill and AGENTS.md snippet both frame it as input, not a verdict — the frontier model keeps final judgment.
