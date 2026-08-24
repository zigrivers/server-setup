"""Log rotation for the always-on stack.

~/ai/logs/orchestrator.log reached 181 MB with no rotation — mlx_lm.server logs every request
and nothing ever trimmed it. Rotation must be copy-truncate: the servers hold the log open, so
renaming the file would leave them writing to an invisible inode.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "rotate-logs.sh"


def run(log_dir: Path, **env_extra: str) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(log_dir.parent.parent), "LOG_DIR": str(log_dir)}
    env.update(env_extra)
    return subprocess.run(["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60, check=True)


def test_rotates_a_large_log_in_place(tmp_path: Path) -> None:
    log_dir = tmp_path / "ai" / "logs"
    log_dir.mkdir(parents=True)
    big = log_dir / "orchestrator.log"
    big.write_text("x" * 2048)
    inode_before = big.stat().st_ino

    run(log_dir, MAX_BYTES="1024")

    # Same inode: an open file handle in the running server keeps working.
    assert big.stat().st_ino == inode_before
    assert big.stat().st_size == 0
    assert (log_dir / "orchestrator.log.1").read_text() == "x" * 2048


def test_leaves_a_small_log_alone(tmp_path: Path) -> None:
    log_dir = tmp_path / "ai" / "logs"
    log_dir.mkdir(parents=True)
    small = log_dir / "meter.log"
    small.write_text("hello")

    run(log_dir, MAX_BYTES="1024")

    assert small.read_text() == "hello"
    assert not (log_dir / "meter.log.1").exists()


def test_keeps_only_one_previous_copy(tmp_path: Path) -> None:
    log_dir = tmp_path / "ai" / "logs"
    log_dir.mkdir(parents=True)
    log = log_dir / "orchestrator.log"
    log.write_text("first" * 500)
    run(log_dir, MAX_BYTES="1024")
    log.write_text("second" * 500)
    run(log_dir, MAX_BYTES="1024")

    assert (log_dir / "orchestrator.log.1").read_text() == "second" * 500
    assert not (log_dir / "orchestrator.log.2").exists()


def test_survives_a_missing_log_dir(tmp_path: Path) -> None:
    # A fresh machine has no logs yet; rotation must not fail the launchd job.
    run(tmp_path / "nope", MAX_BYTES="1024")
