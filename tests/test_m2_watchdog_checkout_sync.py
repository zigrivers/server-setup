"""M2's clone of this repo drifts, silently, until something is expected to work and doesn't.

Found 2026-08-25: M2's checkout at ~/ai/local-ai-stack was 10 commits behind, so a launcher fix
landed that morning was still inert there. Nothing pulls it, and nothing reports that it is stale —
the only symptom is a restart that changes nothing.

The watchdog now pulls it once a day. The rules that matter: never merge or discard work someone
did on M2, never restart a model server as a side effect of a code change, and only interrupt the
operator when a restart is actually needed to apply what was pulled.
"""

import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"

SERVED_MODEL = "/Users/admin/ai/models/developer-qwen38-27b-8bit"


class Watchdog:
    """One tick with a reachable M2 and an ssh stub whose reply we choose."""

    def __init__(self, tmp_path: Path, ssh_reply: str, ssh_exit: int = 0) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.bin_dir = self.home / ".local" / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        (self.home / "ai" / "logs").mkdir(parents=True, exist_ok=True)

        self.watchdog_log = tmp_path / "watchdog.log"
        self.notifications = tmp_path / "notifications.txt"
        self.sync_state = tmp_path / "sync.state"

        (self.bin_dir / "curl").write_text(
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
        (self.bin_dir / "curl").chmod(0o755)
        (self.bin_dir / "nc").write_text("#!/bin/sh\nexit 0\n")  # M2 reachable
        (self.bin_dir / "nc").chmod(0o755)
        (self.bin_dir / "ssh").write_text(
            f"#!/bin/sh\ncat <<'REPLY'\n{ssh_reply}\nREPLY\nexit {ssh_exit}\n"
        )
        (self.bin_dir / "ssh").chmod(0o755)
        (self.bin_dir / "launchpad").write_text(
            f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{self.notifications}"\n'
        )
        (self.bin_dir / "launchpad").chmod(0o755)

    def tick(self, **extra_env: str) -> None:
        env = {
            "PATH": f"{self.bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.home),
            "M2_HOST": "192.0.2.1",
            "M2_PORTS": "8002",
            "M2_WATCHDOG_LOG": str(self.watchdog_log),
            "M2_WATCHDOG_STATE": str(self.tmp / "watchdog.state"),
            "ORCH_STATE": str(self.tmp / "orch.state"),
            "ORCH_LOG": str(self.home / "ai" / "logs" / "orchestrator.log"),
            "WORKER_STATE": str(self.tmp / "workers.state"),
            "M2_SYNC_STATE": str(self.sync_state),
            "TELEMETRY_DB": str(self.tmp / "telemetry.db"),
            "ORCH_PROBE_INTERVAL": "999999",
        }
        env.update(extra_env)
        subprocess.run(["/bin/bash", str(SCRIPT)], env=env, timeout=60, check=True)

    def log(self) -> str:
        return self.watchdog_log.read_text() if self.watchdog_log.exists() else ""

    def notified(self) -> str:
        return self.notifications.read_text() if self.notifications.exists() else ""


def test_a_launcher_change_asks_for_a_restart(tmp_path: Path) -> None:
    """Pulling does not apply a launcher change — only a model reload does, and that is the operator's call."""
    wd = Watchdog(tmp_path, "MOVED 1ceaa82 f4c9b77\nscripts/start-developer.sh\nscripts/start-reviewer.sh")
    wd.tick()
    assert "M2 checkout updated 1ceaa82..f4c9b77" in wd.log()
    assert "start-developer.sh" in wd.notified(), "a launcher change is useless until someone restarts"


def test_an_ordinary_change_does_not_interrupt_anyone(tmp_path: Path) -> None:
    """Docs and tests moving is not worth a notification."""
    wd = Watchdog(tmp_path, "MOVED 1ceaa82 f4c9b77")
    wd.tick()
    assert "M2 checkout updated" in wd.log()
    assert wd.notified() == ""


def test_an_up_to_date_checkout_is_silent(tmp_path: Path) -> None:
    """This runs daily forever; 'still fine' must not fill the log."""
    wd = Watchdog(tmp_path, "CURRENT f4c9b77")
    wd.tick()
    assert "checkout" not in wd.log()
    assert wd.notified() == ""


def test_a_diverged_checkout_is_reported_not_forced(tmp_path: Path) -> None:
    """Someone may have edited a script directly on M2. Never merge or discard that."""
    wd = Watchdog(tmp_path, "PULLFAILED")
    wd.tick()
    assert "would not fast-forward" in wd.log()
    assert "stuck" in wd.notified()


def test_a_machine_without_a_checkout_is_not_an_error(tmp_path: Path) -> None:
    wd = Watchdog(tmp_path, "NOREPO")
    wd.tick()
    assert "nothing to sync" in wd.log()
    assert wd.notified() == ""


def test_it_runs_at_most_once_a_day(tmp_path: Path) -> None:
    """The watchdog fires every 60s; a git pull per minute would be absurd."""
    wd = Watchdog(tmp_path, "MOVED aaa1111 bbb2222")
    wd.tick()
    first = wd.log()
    wd.tick()
    assert wd.log() == first, "second tick within the interval must not pull again"
    assert wd.sync_state.exists()


def test_the_interval_is_configurable(tmp_path: Path) -> None:
    wd = Watchdog(tmp_path, "MOVED aaa1111 bbb2222")
    wd.tick(M2_SYNC_INTERVAL="0")
    wd.tick(M2_SYNC_INTERVAL="0")
    assert wd.log().count("M2 checkout updated") == 2


def test_dry_run_pulls_nothing(tmp_path: Path) -> None:
    wd = Watchdog(tmp_path, "MOVED aaa1111 bbb2222")
    wd.tick(M2_WATCHDOG_DRYRUN="1")
    assert "[dry-run]" in wd.log()
    assert "M2 checkout updated" not in wd.log()
    assert wd.notified() == ""


def test_an_unreachable_m2_does_not_look_like_a_stuck_checkout(tmp_path: Path) -> None:
    wd = Watchdog(tmp_path, "", ssh_exit=255)
    wd.tick()
    assert "could not reach" in wd.log()
    assert wd.notified() == "", "an unreachable M2 is the reachability path's job, not this one"
