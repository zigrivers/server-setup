"""While M2 stays down, the watchdog must restart the meter once, not once per cooldown.

Regression test for the November 2026 outage: M2 was unreachable for eleven days and
the watchdog ran `launchctl kickstart -k` on the meter after every 300-second cooldown
"to clear stale connections". That was 2,776 meter restarts and 3,486 EADDRINUSE
crashes, which lost telemetry and failed nightly reports. A meter restart can only
help at the moment M2 drops; when M2 comes back, the separate meter-wedged path
restarts the meter if it is still stuck.
"""

import socket
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"

# Exactly what launchd hands a LaunchAgent that declares no EnvironmentVariables.
LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# RFC 5737 TEST-NET-1 — guaranteed unreachable, so the worker probe takes the down branch.
UNREACHABLE = "192.0.2.1"

METER_LABEL = "test.meter"


def test_meter_is_restarted_once_while_m2_stays_down(tmp_path):
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (home / "ai" / "logs").mkdir(parents=True)

    # The watchdog puts ~/.local/bin first on PATH, so these stand in for the real tools.
    calls = tmp_path / "launchctl-calls.txt"
    for name, body in (
        ("launchctl", f'printf \'%s\\n\' "$*" >> "{calls}"\n'),
        ("launchpad", "exit 0\n"),
    ):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\n" + body)
        stub.chmod(0o755)

    # A live second path makes the watchdog skip Wake-on-LAN, so no real packet is sent.
    alt = socket.socket()
    alt.bind(("127.0.0.1", 0))
    alt.listen(8)

    log = tmp_path / "wd.log"
    env = {
        "PATH": LAUNCHD_PATH,
        "HOME": str(home),
        "M2_HOST": UNREACHABLE,
        "M2_PORTS": "8002",
        "M2_ALT_HOST": "127.0.0.1",
        "M2_ALT_PORT": str(alt.getsockname()[1]),
        "METER_LABEL": METER_LABEL,
        "ORCH_URL": f"http://{UNREACHABLE}:8001",
        "ORCH_PROBE_TIMEOUT": "1",
        # Zero cooldown: every tick is past the cooldown, as after 300 s in production.
        "M2_RECOVER_COOLDOWN": "0",
        "M2_WATCHDOG_LOG": str(log),
        "M2_WATCHDOG_STATE": str(tmp_path / "wd.state"),
        "ORCH_STATE": str(tmp_path / "orch.state"),
        "TELEMETRY_DB": str(tmp_path / "telemetry.db"),
    }
    try:
        for _ in range(3):
            subprocess.run(["/bin/bash", str(SCRIPT)], env=env, timeout=180, check=False)
    finally:
        alt.close()

    text = log.read_text()
    assert text.count("M2 DOWN") == 3, f"expected three down ticks. Log:\n{text}"
    assert text.count("skipping Wake-on-LAN") == 3, f"a real WoL may have been sent. Log:\n{text}"

    meter_restarts = [
        line for line in (calls.read_text() if calls.exists() else "").splitlines()
        if line.startswith("kickstart") and line.endswith(METER_LABEL)
    ]
    assert len(meter_restarts) == 1, (
        f"meter restarted {len(meter_restarts)} times across three down ticks; "
        f"it must restart only when M2 first drops. Log:\n{text}"
    )
