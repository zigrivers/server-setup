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


def test_review_base_url_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("LOCAL_REVIEW_BASE_URL", "http://example:9/v1")
    monkeypatch.setenv("ORCH_BASE_URL", "http://127.0.0.1:8001/v1")
    assert server._review_base_url() == "http://example:9/v1"


def test_review_base_url_defaults_to_orchestrator_not_reviewer(monkeypatch):
    monkeypatch.delenv("LOCAL_REVIEW_BASE_URL", raising=False)
    monkeypatch.setenv("ORCH_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("REVIEW_BASE_URL", "http://10.10.10.2:8003/v1")
    # The slow dense reviewer must NOT be the default target.
    assert server._review_base_url() == "http://127.0.0.1:8001/v1"


def test_review_base_url_hardcoded_fallback(monkeypatch):
    monkeypatch.delenv("LOCAL_REVIEW_BASE_URL", raising=False)
    monkeypatch.delenv("ORCH_BASE_URL", raising=False)
    assert server._review_base_url() == "http://127.0.0.1:8001/v1"


def test_review_max_tokens_default_override_and_invalid(monkeypatch):
    monkeypatch.delenv("LOCAL_REVIEW_MAX_TOKENS", raising=False)
    assert server._review_max_tokens() == 3000
    monkeypatch.setenv("LOCAL_REVIEW_MAX_TOKENS", "1200")
    assert server._review_max_tokens() == 1200
    monkeypatch.setenv("LOCAL_REVIEW_MAX_TOKENS", "garbage")
    assert server._review_max_tokens() == 3000


def test_local_review_targets_orchestrator_and_flags_truncation(git_repo, monkeypatch):
    (git_repo / "a.txt").write_text("changed\n")
    monkeypatch.delenv("LOCAL_REVIEW_BASE_URL", raising=False)
    monkeypatch.setenv("ORCH_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setattr(server, "_review_model", lambda base, timeout=10: "M")
    captured = {}

    def fake_post(url, payload, timeout):
        captured["url"] = url
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "REVIEW BODY"}, "finish_reason": "length"}]}

    monkeypatch.setattr(server, "_post_json", fake_post)
    out = server.local_review(workspace=str(git_repo))
    assert "REVIEW BODY" in out
    assert captured["url"].startswith("http://127.0.0.1:8001/v1")
    assert captured["payload"]["max_tokens"] == 3000
    # Thinking must be disabled so the orchestrator returns content, not reasoning.
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "127.0.0.1:8001" in out
    assert "truncated" in out.lower()  # finish_reason == length must be surfaced


def test_local_review_empty_content_degrades_gracefully(git_repo, monkeypatch):
    # Regression: a thinking model that runs out of tokens returns a message with
    # no `content` key. local_review must not KeyError — it must explain.
    (git_repo / "a.txt").write_text("changed\n")
    monkeypatch.setattr(server, "_review_model", lambda base, timeout=10: "M")
    monkeypatch.setattr(
        server,
        "_post_json",
        lambda url, payload, timeout: {"choices": [{"message": {"role": "assistant", "reasoning": "..."}, "finish_reason": "length"}]},
    )
    out = server.local_review(workspace=str(git_repo))
    assert "no answer" in out.lower()
    assert "LOCAL_REVIEW_MAX_TOKENS" in out


def test_local_review_timeout_returns_clear_message(git_repo, monkeypatch):
    (git_repo / "a.txt").write_text("changed\n")
    monkeypatch.setattr(server, "_review_model", lambda base, timeout=10: "M")

    def boom(url, payload, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(server, "_post_json", boom)
    out = server.local_review(workspace=str(git_repo))
    assert "timed out" in out.lower() or "failed" in out.lower()
    assert "LOCAL_REVIEW" in out  # actionable guidance names the override knobs
