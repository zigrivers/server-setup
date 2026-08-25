"""The watchdog must catch a crashed mlx generation thread from the log, and must never guess a model id.

Two failures on 2026-08-24 motivate this file.

1. mlx-lm leaks live Metal buffer descriptors while decoding and throws
   `[metal::malloc] Resource limit (499000) exceeded`, killing the server's generation thread. The
   process keeps answering /v1/models with 200 while every completion hangs, so the completion probe
   needed ~9 minutes to call it a wedge — four times in 90 minutes. The traceback is unambiguous, so
   the watchdog now reads the server log every tick and restarts on the first sight of a crash.

2. The orchestrator probe hardcoded the bf16 model path (65 GB) while the stack serves mixed9
   (38 GB). To mlx_lm.server the `model` field is a load instruction, so only the meter's
   METER_ORCH_MODEL pin stopped that probe from loading a second copy. The probe now asks the
   endpoint what it is serving.
"""

import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"

SERVED_MODEL = "/Users/kenallred/ai/models/orchestrator-qwen36-35b-a3b-heretic-mixed9"
CRASH_TRACEBACK = textwrap.dedent(
    """\
    Exception in thread Thread-1 (_generate):
    Traceback (most recent call last):
      File "mlx_lm/generate.py", line 1369, in _step
        mx.async_eval(self._next_tokens, self._next_logprobs, token_context)
    RuntimeError: [metal::malloc] Resource limit (499000) exceeded.
    """
)


class Watchdog:
    """One watchdog tick against a fake stack, with the orchestrator log under our control."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        bin_dir = self.home / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (self.home / "ai" / "logs").mkdir(parents=True, exist_ok=True)

        self.orch_log = self.home / "ai" / "logs" / "orchestrator.log"
        self.watchdog_log = tmp_path / "watchdog.log"
        self.orch_state = tmp_path / "orchestrator.state"
        self.requests = tmp_path / "curl-requests.txt"

        # A probe asking for an http_code gets "200"; a plain GET of /v1/models gets the model list.
        # That split matters: orch_model() parses the list, while probe_meter/probe_orchestrator
        # only read the status code.
        fake_curl = bin_dir / "curl"
        fake_curl.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                printf '%s\\n' "$*" >> "{self.requests}"
                case "$*" in
                  *http_code*) printf '200' ;;
                  */v1/models*) printf '{{"object":"list","data":[{{"id":"{SERVED_MODEL}","object":"model"}}]}}' ;;
                  *) printf '200' ;;
                esac
                """
            )
        )
        fake_curl.chmod(0o755)
        fake_nc = bin_dir / "nc"
        fake_nc.write_text("#!/bin/sh\nexit 0\n")
        fake_nc.chmod(0o755)
        self.bin_dir = bin_dir

    def tick(self, **extra_env: str) -> None:
        env = {
            "PATH": f"{self.bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.home),
            "M2_HOST": "192.0.2.1",
            "M2_PORTS": "8002",
            "M2_WATCHDOG_DRYRUN": "1",
            "M2_WATCHDOG_LOG": str(self.watchdog_log),
            "M2_WATCHDOG_STATE": str(self.tmp / "watchdog.state"),
            "ORCH_STATE": str(self.orch_state),
            "ORCH_LOG": str(self.orch_log),
            "TELEMETRY_DB": str(self.tmp / "telemetry.db"),
            # Force the completion probe to run on every tick so model-id assertions are reachable.
            "ORCH_PROBE_INTERVAL": "0",
        }
        env.update(extra_env)
        subprocess.run(["/bin/bash", str(SCRIPT)], env=env, timeout=60, check=True)

    def log(self) -> str:
        return self.watchdog_log.read_text() if self.watchdog_log.exists() else ""

    def curl_calls(self) -> list[str]:
        return self.requests.read_text().splitlines() if self.requests.exists() else []


def test_crash_in_the_server_log_triggers_a_restart(tmp_path: Path) -> None:
    """A generation-thread traceback is proof of a wedge — no need to wait for probes to time out."""
    wd = Watchdog(tmp_path)
    wd.orch_log.write_text("127.0.0.1 - - [24/Aug/2026 14:30:00] \"GET /v1/models HTTP/1.1\" 200 -\n")
    wd.tick()  # first sight of the log: adopt its end, restart nothing
    assert "crashed" not in wd.log()

    with wd.orch_log.open("a") as fh:
        fh.write(CRASH_TRACEBACK)
    wd.tick()
    assert "orchestrator generation thread crashed" in wd.log()


def test_a_crash_already_in_the_log_at_startup_is_not_replayed(tmp_path: Path) -> None:
    """Deploying this while today's recovered crashes sit in the log must not restart the 35B."""
    wd = Watchdog(tmp_path)
    wd.orch_log.write_text(CRASH_TRACEBACK * 4)
    wd.tick()
    assert "crashed" not in wd.log()
    # And a quiet tick afterwards stays quiet — the position was persisted, not just held in memory.
    wd.orch_log.open("a").write("127.0.0.1 - - [24/Aug/2026 16:10:00] \"GET /v1/models HTTP/1.1\" 200 -\n")
    wd.tick()
    assert "crashed" not in wd.log()


def test_a_truncated_log_does_not_replay_old_crashes(tmp_path: Path) -> None:
    """After rotate-logs.sh truncates the log, the stale offset must not be treated as new bytes."""
    wd = Watchdog(tmp_path)
    wd.orch_log.write_text("x" * 5000)
    wd.tick()
    wd.orch_log.write_text("fresh start\n")  # now much shorter than the recorded position
    wd.tick()
    assert "crashed" not in wd.log()


def test_the_probe_uses_the_model_the_endpoint_reports(tmp_path: Path) -> None:
    """Sending a path mlx is not serving loads a SECOND copy — always ask, never hardcode."""
    wd = Watchdog(tmp_path)
    wd.orch_log.write_text("")
    wd.tick()
    completions = [c for c in wd.curl_calls() if "/v1/chat/completions" in c]
    assert completions, "expected the orchestrator completion probe to run"
    for call in completions:
        assert SERVED_MODEL in call, f"probe did not use the served model id: {call}"
        assert "bf16" not in call, f"probe named a model the server is not running: {call}"


def test_an_unreachable_endpoint_is_not_reported_as_wedged(tmp_path: Path) -> None:
    """If /v1/models cannot be read we cannot know the model id — skip, do not guess or restart."""
    wd = Watchdog(tmp_path)
    wd.orch_log.write_text("")
    (wd.bin_dir / "curl").write_text("#!/bin/sh\nexit 7\n")  # connection refused
    (wd.bin_dir / "curl").chmod(0o755)
    wd.tick()
    assert "WEDGED" not in wd.log()
    assert "crashed" not in wd.log()
