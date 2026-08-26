"""M2's workers get a real completion probe, so an idle wedge is found and the dashboard stays honest.

Two problems this fixes, both seen on 2026-08-25.

M2's health was read only from whatever the user's own traffic happened to reveal. With no traffic
there was nothing to read, so a wedge on an unused endpoint would sit undiscovered until they next
tried it — the overnight outage was caught only because an OpenCode session was hammering it.

And the dashboard could not tell idle from dead. The orchestrator always looked green because its
own probe kept its "last seen" fresh; healthy M2 endpoints decayed to grey after six idle hours and
were reported as down. The probe goes through the meter precisely so it lands in telemetry and
keeps that row current.
"""

import subprocess
import sqlite3
import textwrap
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"

SERVED_MODEL = "/Users/admin/ai/models/developer-qwen38-27b-8bit"


class Watchdog:
    """One tick with a reachable M2 and a curl stub whose completion status we choose."""

    def __init__(self, tmp_path: Path, completion_code: str = "200") -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.bin_dir = self.home / ".local" / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        (self.home / "ai" / "logs").mkdir(parents=True, exist_ok=True)

        self.watchdog_log = tmp_path / "watchdog.log"
        self.curl_calls = tmp_path / "curl-calls.txt"
        self.ssh_calls = tmp_path / "ssh-calls.txt"
        self.telemetry = tmp_path / "telemetry.db"

        # Meter /v1/models probes still answer 200 so the reachability path stays happy; only the
        # chat completion carries the code under test.
        (self.bin_dir / "curl").write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                printf '%s\\n' "$*" >> "{self.curl_calls}"
                case "$*" in
                  *chat/completions*) printf '{completion_code}' ;;
                  *http_code*) printf '200' ;;
                  */v1/models*) printf '{{"object":"list","data":[{{"id":"{SERVED_MODEL}"}}]}}' ;;
                  *) printf '200' ;;
                esac
                """
            )
        )
        (self.bin_dir / "curl").chmod(0o755)
        (self.bin_dir / "nc").write_text("#!/bin/sh\nexit 0\n")
        (self.bin_dir / "nc").chmod(0o755)
        (self.bin_dir / "ssh").write_text(
            f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{self.ssh_calls}"\necho NOREPO\nexit 0\n'
        )
        (self.bin_dir / "ssh").chmod(0o755)

    def with_recent_success(self, upstream: str) -> None:
        """Real client traffic succeeded moments ago — the endpoint is busy, not wedged."""
        db = sqlite3.connect(self.telemetry)
        db.execute("CREATE TABLE IF NOT EXISTS requests (ts INTEGER, client TEXT, upstream TEXT, "
                   "kind TEXT, error_class TEXT, status INTEGER)")
        db.execute("INSERT INTO requests VALUES (?,?,?,?,?,?)",
                   (int(time.time() * 1000) - 5_000, "opencode", upstream, "chat", "ok", 200))
        db.commit()
        db.close()

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
            "M2_SYNC_STATE": str(self.tmp / "sync.state"),
            "M2_SYNC_INTERVAL": "999999",
            "TELEMETRY_DB": str(self.telemetry),
            "ORCH_PROBE_INTERVAL": "999999",
            "M2_PROBE_INTERVAL": "0",
        }
        env.update(extra_env)
        subprocess.run(["/bin/bash", str(SCRIPT)], env=env, timeout=60, check=True)

    def log(self) -> str:
        return self.watchdog_log.read_text() if self.watchdog_log.exists() else ""

    def completions(self) -> list[str]:
        if not self.curl_calls.exists():
            return []
        return [c for c in self.curl_calls.read_text().splitlines() if "chat/completions" in c]

    def kills(self) -> list[str]:
        if not self.ssh_calls.exists():
            return []
        return [c for c in self.ssh_calls.read_text().splitlines() if "pkill" in c]


def test_the_probe_goes_through_the_meter_so_the_dashboard_sees_it(tmp_path: Path) -> None:
    """Probing :8002 on M2 directly would work but leave the dashboard row stale and grey."""
    wd = Watchdog(tmp_path)
    wd.tick()
    targets = [c for c in wd.completions() if "127.0.0.1:900" in c]
    assert any(":9002/v1/chat/completions" in c for c in targets), "developer must be probed via the meter"
    assert any(":9003/v1/chat/completions" in c for c in targets), "reviewer must be probed via the meter"


def test_the_probe_identifies_itself_and_uses_the_served_model(tmp_path: Path) -> None:
    """A model id mlx is not already serving is an instruction to load a SECOND copy."""
    wd = Watchdog(tmp_path)
    wd.tick()
    for call in wd.completions():
        assert "Authorization: Bearer watchdog" in call, "probes must be attributable in the dashboard"
        assert SERVED_MODEL in call, f"probe did not use the served model id: {call}"


def test_the_probe_is_tiny(tmp_path: Path) -> None:
    """This runs every 5 minutes forever on two endpoints; it must not be real work."""
    wd = Watchdog(tmp_path)
    wd.tick()
    for call in wd.completions():
        assert '"max_tokens":1' in call.replace(" ", ""), f"probe is not a one-token generation: {call}"


def test_an_idle_wedge_is_caught_without_any_client_traffic(tmp_path: Path) -> None:
    """The whole point: no user traffic, empty telemetry, and the wedge is still found."""
    wd = Watchdog(tmp_path, completion_code="000")
    wd.tick()
    assert "completion probe failing (x1)" in wd.log(), "one bad probe should watch, not restart"
    assert wd.kills() == []
    wd.tick()
    assert "WEDGED" in wd.log()
    assert any("--port 8002" in k for k in wd.kills())


def test_a_busy_endpoint_is_not_called_wedged(tmp_path: Path) -> None:
    """mlx serializes, so a probe times out behind a long generation. Recent real traffic proves life."""
    wd = Watchdog(tmp_path, completion_code="000")
    wd.with_recent_success("developer")
    wd.tick()
    wd.tick()
    assert "busy, not wedged" in wd.log()
    assert not any("--port 8002" in k for k in wd.kills()), "restarting a busy server throws away its work"


def test_probes_are_throttled_to_their_own_interval(tmp_path: Path) -> None:
    """A real generation on every 60s tick would be 2,880 pointless inferences a day."""
    wd = Watchdog(tmp_path)
    wd.tick(M2_PROBE_INTERVAL="300")
    first = len(wd.completions())
    assert first >= 2, "both workers should be probed on the first tick"
    wd.tick(M2_PROBE_INTERVAL="300")
    assert len(wd.completions()) == first, "a tick inside the interval must not re-probe"


def test_recovery_is_announced(tmp_path: Path) -> None:
    """After a restart the operator should learn it came back, not just that it broke."""
    wd = Watchdog(tmp_path, completion_code="000")
    wd.tick()
    (wd.bin_dir / "curl").write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{wd.curl_calls}"\n'
        'case "$*" in *chat/completions*) printf \'200\' ;; *http_code*) printf \'200\' ;; '
        f'*/v1/models*) printf \'{{"object":"list","data":[{{"id":"{SERVED_MODEL}"}}]}}\' ;; '
        '*) printf \'200\' ;; esac\n'
    )
    (wd.bin_dir / "curl").chmod(0o755)
    wd.tick()
    assert "RECOVERED" in wd.log()
