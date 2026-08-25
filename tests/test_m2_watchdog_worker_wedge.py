"""M2's workers wedge the same way the orchestrator does, and nothing was watching them.

On 2026-08-24/25 the developer and reviewer servers both hit
`[metal::malloc] Resource limit (499000) exceeded`, which kills mlx's generation thread while the
process keeps answering /v1/models with 200. They served nothing for roughly seven hours — 126
failed requests — because the watchdog only ever looked at the M1 orchestrator, and M2's ports were
reachable the whole time.

The verdict is drawn from the meter's own telemetry rather than another log grep across the link: an
upstream carrying several chat failures and NO successes is wedged by definition. Only the restart
crosses to M2, and it needs no sudo — the workers are LaunchDaemons with KeepAlive
SuccessfulExit=false, so killing the process makes launchd load a fresh one.
"""

import sqlite3
import subprocess
import textwrap
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"

SERVED_MODEL = "/Users/admin/ai/models/developer-qwen38-27b-8bit"


def make_telemetry(db_path: Path, rows: list[tuple[str, str, int]]) -> None:
    """rows: (upstream, error_class, seconds_ago). Only the columns the watchdog reads are real."""
    db = sqlite3.connect(db_path)
    db.execute(
        "CREATE TABLE requests (ts INTEGER, client TEXT, upstream TEXT, kind TEXT, "
        "error_class TEXT, status INTEGER)"
    )
    now_ms = int(time.time() * 1000)
    db.executemany(
        "INSERT INTO requests (ts, client, upstream, kind, error_class, status) VALUES (?,?,?,?,?,?)",
        [
            (now_ms - ago * 1000, "opencode", upstream, "chat", error_class, 0)
            for upstream, error_class, ago in rows
        ],
    )
    db.commit()
    db.close()


class Watchdog:
    """One watchdog tick with a reachable M2, fake ssh, and telemetry we control."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.bin_dir = self.home / ".local" / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        (self.home / "ai" / "logs").mkdir(parents=True, exist_ok=True)

        self.ssh_calls = tmp_path / "ssh-calls.txt"
        self.watchdog_log = tmp_path / "watchdog.log"
        self.telemetry = tmp_path / "telemetry.db"

        fake_curl = self.bin_dir / "curl"
        fake_curl.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                case "$*" in
                  *http_code*) printf '200' ;;
                  */v1/models*) printf '{{"object":"list","data":[{{"id":"{SERVED_MODEL}"}}]}}' ;;
                  *) printf '200' ;;
                esac
                """
            )
        )
        fake_curl.chmod(0o755)
        (self.bin_dir / "nc").write_text("#!/bin/sh\nexit 0\n")  # M2 reachable
        (self.bin_dir / "nc").chmod(0o755)
        fake_ssh = self.bin_dir / "ssh"
        fake_ssh.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{self.ssh_calls}"\nexit 0\n')
        fake_ssh.chmod(0o755)

    def tick(self, **extra_env: str) -> None:
        env = {
            "PATH": f"{self.bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.home),
            "M2_HOST": "192.0.2.1",
            "M2_PORTS": "8002",
            "M2_WATCHDOG_LOG": str(self.watchdog_log),
            "M2_WATCHDOG_STATE": str(self.tmp / "watchdog.state"),
            "ORCH_STATE": str(self.tmp / "orchestrator.state"),
            "ORCH_LOG": str(self.home / "ai" / "logs" / "orchestrator.log"),
            "WORKER_STATE": str(self.tmp / "workers.state"),
            "TELEMETRY_DB": str(self.telemetry),
            # Keep the orchestrator's own completion probe out of the way of these assertions.
            "ORCH_PROBE_INTERVAL": "999999",
        }
        env.update(extra_env)
        subprocess.run(["/bin/bash", str(SCRIPT)], env=env, timeout=60, check=True)

    def log(self) -> str:
        return self.watchdog_log.read_text() if self.watchdog_log.exists() else ""

    def ssh(self) -> list[str]:
        return self.ssh_calls.read_text().splitlines() if self.ssh_calls.exists() else []


def test_an_upstream_with_only_failures_is_restarted(tmp_path: Path) -> None:
    wd = Watchdog(tmp_path)
    make_telemetry(wd.telemetry, [("developer", "timeout", ago) for ago in (60, 120, 180, 240)])
    wd.tick()
    assert "developer WEDGED" in wd.log()
    kills = [c for c in wd.ssh() if "pkill" in c]
    assert kills, "expected a kill over ssh"
    assert "--port 8002" in kills[0]
    # The pattern must not match the remote shell that is running pkill, or it kills its own session.
    assert "mlx_lm[.]server" in kills[0]


def test_a_working_upstream_is_left_alone(tmp_path: Path) -> None:
    """Failures alongside successes are ordinary life — long prompts time out on a healthy server."""
    wd = Watchdog(tmp_path)
    make_telemetry(
        wd.telemetry,
        [("developer", "timeout", 60), ("developer", "timeout", 120),
         ("developer", "timeout", 180), ("developer", "ok", 90)],
    )
    wd.tick()
    assert "WEDGED" not in wd.log()
    assert not [c for c in wd.ssh() if "pkill" in c]


def test_a_quiet_upstream_is_left_alone(tmp_path: Path) -> None:
    """No traffic is not evidence of a wedge — do not reload a 28 GB model because nobody called."""
    wd = Watchdog(tmp_path)
    make_telemetry(wd.telemetry, [])
    wd.tick()
    assert "WEDGED" not in wd.log()
    assert not [c for c in wd.ssh() if "pkill" in c]


def test_one_or_two_failures_are_not_enough(tmp_path: Path) -> None:
    wd = Watchdog(tmp_path)
    make_telemetry(wd.telemetry, [("developer", "timeout", 60), ("developer", "timeout", 120)])
    wd.tick()
    assert "WEDGED" not in wd.log()


def test_old_failures_fall_out_of_the_window(tmp_path: Path) -> None:
    """A wedge that was already recovered hours ago must not trigger a fresh restart."""
    wd = Watchdog(tmp_path)
    make_telemetry(wd.telemetry, [("developer", "timeout", ago) for ago in (4000, 5000, 6000)])
    wd.tick()
    assert "WEDGED" not in wd.log()


def test_a_restart_is_not_repeated_every_tick(tmp_path: Path) -> None:
    """The model takes minutes to reload; a second kill inside the cooldown would restart the reload."""
    wd = Watchdog(tmp_path)
    make_telemetry(wd.telemetry, [("developer", "timeout", ago) for ago in (60, 120, 180, 240)])
    wd.tick()
    assert len([c for c in wd.ssh() if "pkill" in c]) == 1
    wd.tick()  # telemetry still looks wedged — the model is still loading
    assert len([c for c in wd.ssh() if "pkill" in c]) == 1


def test_both_workers_are_watched(tmp_path: Path) -> None:
    """The reviewer wedged too, and on its own schedule — one shared verdict would have missed it."""
    wd = Watchdog(tmp_path)
    make_telemetry(wd.telemetry, [("reviewer", "timeout", ago) for ago in (60, 120, 180, 240)])
    wd.tick()
    assert "reviewer WEDGED" in wd.log()
    kills = [c for c in wd.ssh() if "pkill" in c]
    assert kills and "--port 8003" in kills[0]


def test_an_unreachable_m2_is_not_called_a_wedge(tmp_path: Path) -> None:
    """When the link is down every request fails; that is the reachability path, not a wedge."""
    wd = Watchdog(tmp_path)
    make_telemetry(wd.telemetry, [("developer", "timeout", ago) for ago in (60, 120, 180, 240)])
    (wd.bin_dir / "nc").write_text("#!/bin/sh\nexit 1\n")
    (wd.bin_dir / "nc").chmod(0o755)
    wd.tick(M2_WATCHDOG_DRYRUN="1")
    assert "WEDGED" not in wd.log()
    assert not [c for c in wd.ssh() if "pkill" in c]
