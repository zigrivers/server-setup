"""The watchdog's own probes must be labelled and cheap.

Before 2026-08-24 the watchdog's meter probes carried no API key (so they landed in the
dashboard as client 'unknown', the single largest "client" on the stack) and its orchestrator
completion probe ran every 60s straight at :8001, bypassing the meter — 1,766 real 35B
generations a day that the dashboard never saw.
"""

import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"


def run_watchdog(tmp_path: Path, *, extra_env: dict[str, str] | None = None) -> list[str]:
    """Run one watchdog tick with fake curl/nc; return the recorded curl invocations."""
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (home / "ai" / "logs").mkdir(parents=True, exist_ok=True)

    receipt = tmp_path / "curl-requests.txt"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            printf '%s\\n' "$*" >> "{receipt}"
            printf '200'
            """
        )
    )
    fake_curl.chmod(0o755)

    fake_nc = bin_dir / "nc"
    fake_nc.write_text("#!/bin/sh\nexit 0\n")
    fake_nc.chmod(0o755)

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "M2_HOST": "192.0.2.1",
        "M2_PORTS": "8002",
        "M2_WATCHDOG_DRYRUN": "1",
        "M2_WATCHDOG_LOG": str(tmp_path / "watchdog.log"),
        "M2_WATCHDOG_STATE": str(tmp_path / "watchdog.state"),
        "ORCH_STATE": str(tmp_path / "orchestrator.state"),
        "TELEMETRY_DB": str(tmp_path / "telemetry.db"),
    }
    env.update(extra_env or {})
    subprocess.run(["/bin/bash", str(SCRIPT)], env=env, timeout=60, check=True)
    return receipt.read_text().splitlines() if receipt.exists() else []


def test_every_probe_identifies_itself_as_the_watchdog(tmp_path: Path) -> None:
    requests = run_watchdog(tmp_path)
    assert requests, "expected the watchdog to probe something"
    for request in requests:
        assert "Authorization: Bearer watchdog" in request, request


def test_orchestrator_probe_goes_through_the_meter(tmp_path: Path) -> None:
    requests = run_watchdog(tmp_path)
    completions = [r for r in requests if "chat/completions" in r]
    assert len(completions) == 1
    # :9001 is the meter's orchestrator port; :8001 is the model server behind it.
    assert "http://127.0.0.1:9001/v1/chat/completions" in completions[0]


def test_orchestrator_probe_is_throttled_between_ticks(tmp_path: Path) -> None:
    first = run_watchdog(tmp_path)
    assert [r for r in first if "chat/completions" in r]
    # A second tick a minute later must NOT re-probe: the interval is 5 minutes.
    second = run_watchdog(tmp_path)
    assert not [r for r in second[len(first):] if "chat/completions" in r]


def test_orchestrator_probe_interval_is_configurable(tmp_path: Path) -> None:
    first = run_watchdog(tmp_path, extra_env={"ORCH_PROBE_INTERVAL": "0"})
    second = run_watchdog(tmp_path, extra_env={"ORCH_PROBE_INTERVAL": "0"})
    assert [r for r in second[len(first):] if "chat/completions" in r]
