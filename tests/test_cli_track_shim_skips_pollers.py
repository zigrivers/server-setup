"""The CLI-usage shim counts human CLI runs, not menu-bar polling.

CodexBar refreshes every 2 minutes and spawns the Grok CLI to read quota. Those spawns went
through this shim, so the dashboard showed ~2,165 'grok requests' a day that nobody asked for
(150,177 rows all-time). A poller in the process ancestry means: run the real tool, skip the ping.
"""

import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "scripts" / "cli-track-shim.sh"


def run_shim(tmp_path: Path, ancestry: list[str]) -> tuple[list[str], str]:
    """Run the shim as `grok` with a faked process ancestry; return (pings, real-tool output)."""
    shim_dir = tmp_path / "cli-shims"
    shim_dir.mkdir()
    (shim_dir / "grok").symlink_to(SHIM)

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real_tool = real_dir / "grok"
    real_tool.write_text("#!/bin/sh\necho REAL-GROK-RAN\n")
    real_tool.chmod(0o755)

    fake_bin = tmp_path / "fake"
    fake_bin.mkdir()
    receipt = tmp_path / "pings.txt"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            printf '%s\\n' "$*" >> "{receipt}"
            """
        )
    )
    fake_curl.chmod(0o755)

    # A fake `ps` serving a canned ancestry: pid N reports command ancestry[N-1] and parent N+1.
    fake_ps = fake_bin / "ps"
    # pids 100, 101, ... so no entry collides with pid 1 (which ends an ancestry walk)
    lines = "\n".join(
        f'  {100 + i}) [ "$FIELD" = comm ] && echo "{name}" || echo "{101 + i}" ;;'
        for i, name in enumerate(ancestry)
    )
    fake_ps.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            # usage: ps -o comm= -p PID   |   ps -o ppid= -p PID
            FIELD=$(echo "$2" | sed 's/=//')
            PID=$4
            case "$PID" in
            {lines}
              *) exit 1 ;;
            esac
            """
        )
    )
    fake_ps.chmod(0o755)

    result = subprocess.run(
        ["/bin/sh", "-c", f'exec -a grok "{shim_dir}/grok"'],
        env={
            "PATH": f"{shim_dir}:{fake_bin}:{real_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "CLI_TRACK_PPID": "100",  # the shim starts its ancestry walk here in tests
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    pings = receipt.read_text().splitlines() if receipt.exists() else []
    return pings, result.stdout


def test_counts_a_run_started_from_a_terminal(tmp_path: Path) -> None:
    pings, out = run_shim(tmp_path, ["zsh", "login", "alacritty"])
    assert "REAL-GROK-RAN" in out
    assert len(pings) == 1


def test_skips_the_ping_when_a_menu_bar_poller_launched_it(tmp_path: Path) -> None:
    pings, out = run_shim(tmp_path, ["CodexBar"])
    assert "REAL-GROK-RAN" in out, "the real tool must still run"
    assert pings == []


def test_finds_the_poller_further_up_the_ancestry(tmp_path: Path) -> None:
    # CodexBar may invoke the CLI through a login shell rather than directly.
    pings, out = run_shim(tmp_path, ["zsh", "CodexBar"])
    assert "REAL-GROK-RAN" in out
    assert pings == []
