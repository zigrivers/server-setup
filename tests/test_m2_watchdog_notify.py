"""The watchdog's notify() must work under launchd's minimal PATH.

Regression test for the 2026-08-02..2026-08-06 incident: `launchpad` lives in
~/.local/bin, which is NOT on launchd's default PATH. Inside notify(),
`command -v launchpad` therefore failed and the trailing `|| true` swallowed it,
so four days of continuous M2-outage notifications silently no-opped and nobody
was told a required MMR review channel was dead.
"""

import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"

# Exactly what launchd hands a LaunchAgent that declares no EnvironmentVariables.
LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def test_notify_reaches_launchpad_under_launchd_path(tmp_path):
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

    env = {
        "PATH": LAUNCHD_PATH,
        "HOME": str(home),
        # RFC 5737 TEST-NET-1 — guaranteed unreachable, so the script takes the
        # "M2 down" branch and must notify.
        "M2_HOST": "192.0.2.1",
        "M2_PORTS": "8002",
        # No second path to M2, so the script cannot rule out a sleeping machine and
        # must take the plain "worker dropped" branch this test was written for.
        # (See test_m2_watchdog_link_vs_sleep.py for the link-down-vs-asleep split.)
        "M2_ALT_HOST": "",
        "ORCH_URL": "http://192.0.2.1:8001",
        "ORCH_PROBE_TIMEOUT": "1",
        # Dry run: no Wake-on-LAN, no launchctl kickstart, no real recovery.
        "M2_WATCHDOG_DRYRUN": "1",
        "M2_WATCHDOG_LOG": str(tmp_path / "wd.log"),
        "M2_WATCHDOG_STATE": str(tmp_path / "wd.state"),
        "ORCH_STATE": str(tmp_path / "orch.state"),
        "TELEMETRY_DB": str(tmp_path / "telemetry.db"),
    }

    subprocess.run(["/bin/bash", str(SCRIPT)], env=env, timeout=180, check=False)

    assert receipt.exists(), (
        "notify() never reached launchpad under launchd's PATH — outage "
        "notifications silently no-op, which is how a 4-day outage went unreported"
    )
    assert "M2 worker dropped" in receipt.read_text()
