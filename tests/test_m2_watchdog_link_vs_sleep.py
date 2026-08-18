"""The watchdog must tell "M2 is asleep/off" apart from "M2 is up, the link is down".

Regression test for the 2026-08-17 incident: the Thunderbolt cable between M1 and
M2 dropped while M2 sat awake with 87 days of uptime. The watchdog probed only
10.10.10.2, saw nothing, sent a Wake-on-LAN packet to an already-awake machine and
concluded "likely asleep/off; manual wake may be needed" — pointing the operator at
the machine when the fault was a cable. A second probe over Tailscale distinguishes
the two, and the advice differs completely: WoL cannot fix a cable.
"""

import socket
import subprocess
import textwrap
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"

# Exactly what launchd hands a LaunchAgent that declares no EnvironmentVariables.
LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# RFC 5737 TEST-NET-1 — guaranteed unreachable, so the worker probe takes the down branch.
UNREACHABLE = "192.0.2.1"


@contextmanager
def listening_port():
    """A real TCP listener, so `nc -z` genuinely succeeds against the alt path."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def run_watchdog(tmp_path, *, alt_host, alt_port):
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (home / "ai" / "logs").mkdir(parents=True)

    receipt = tmp_path / "notified.txt"
    fake = bin_dir / "launchpad"
    fake.write_text(
        textwrap.dedent(f"""\
        #!/bin/sh
        printf '%s\\n' "$*" >> "{receipt}"
        """)
    )
    fake.chmod(0o755)

    log = tmp_path / "wd.log"
    env = {
        "PATH": LAUNCHD_PATH,
        "HOME": str(home),
        "M2_HOST": UNREACHABLE,
        "M2_PORTS": "8002",
        "M2_ALT_HOST": alt_host,
        "M2_ALT_PORT": str(alt_port),
        "ORCH_URL": f"http://{UNREACHABLE}:8001",
        "ORCH_PROBE_TIMEOUT": "1",
        # Dry run: no Wake-on-LAN, no launchctl kickstart, no real recovery.
        "M2_WATCHDOG_DRYRUN": "1",
        "M2_WATCHDOG_LOG": str(log),
        "M2_WATCHDOG_STATE": str(tmp_path / "wd.state"),
        "ORCH_STATE": str(tmp_path / "orch.state"),
        "TELEMETRY_DB": str(tmp_path / "telemetry.db"),
    }
    subprocess.run(["/bin/bash", str(SCRIPT)], env=env, timeout=180, check=False)
    return log.read_text(), (receipt.read_text() if receipt.exists() else "")


def test_link_down_is_not_reported_as_a_sleeping_machine(tmp_path):
    """Alt path answers => the machine is up, so blame the link and skip the WoL."""
    with listening_port() as port:
        log, notified = run_watchdog(tmp_path, alt_host="127.0.0.1", alt_port=port)

    assert "M2 itself is ALIVE" in log, (
        "watchdog did not detect M2 alive on its second path, so it cannot tell a "
        f"dropped cable from a sleeping machine. Log:\n{log}"
    )
    assert "skipping Wake-on-LAN" in log, (
        f"watchdog still tried to wake an already-awake machine. Log:\n{log}"
    )
    assert "check the Thunderbolt cable" in notified, (
        f"operator was not pointed at the cable. Notifications:\n{notified}"
    )
    assert "manual wake" not in notified, (
        f"watchdog still advised a manual wake for an awake machine:\n{notified}"
    )


def test_unreachable_alt_path_keeps_the_original_sleep_diagnosis(tmp_path):
    """Alt path silent => we genuinely cannot rule out sleep; keep the old behaviour."""
    log, notified = run_watchdog(tmp_path, alt_host=UNREACHABLE, alt_port=22)

    assert "M2 itself is ALIVE" not in log, (
        f"claimed M2 was alive with no evidence. Log:\n{log}"
    )
    assert "M2 worker dropped" in notified, (
        f"the original outage alarm regressed. Notifications:\n{notified}"
    )
    assert "check the Thunderbolt cable" not in notified, (
        f"blamed the cable without evidence the machine was up:\n{notified}"
    )
