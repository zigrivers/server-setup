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
