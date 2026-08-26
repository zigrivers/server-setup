import plistlib
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"
INSTALLER = REPO / "scripts" / "install-launchd-machine1.sh"
METER_URL = "http://127.0.0.1:{port}/v1/models"


@pytest.mark.parametrize(
    ("meter_ports", "expected_ports"),
    [
        (None, [9002, 9003, 9004, 9006]),
        ("9006", [9006]),
    ],
)
def test_meter_routes_cover_required_mmr_ports_and_honor_override(
    tmp_path: Path,
    meter_ports: str | None,
    expected_ports: list[int],
) -> None:
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (home / "ai" / "logs").mkdir(parents=True)

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
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "M2_HOST": "192.0.2.1",
        "M2_PORTS": "8002",
        "ORCH_URL": "http://127.0.0.1:8001",
        "M2_WATCHDOG_DRYRUN": "1",
        "M2_WATCHDOG_LOG": str(tmp_path / "watchdog.log"),
        "M2_WATCHDOG_STATE": str(tmp_path / "watchdog.state"),
        "ORCH_STATE": str(tmp_path / "orchestrator.state"),
        "TELEMETRY_DB": str(tmp_path / "telemetry.db"),
    }
    if meter_ports is not None:
        env["METER_PORTS"] = meter_ports

    subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        env=env,
        timeout=30,
        check=True,
    )

    requests = receipt.read_text().splitlines()
    expected_urls = {METER_URL.format(port=port) for port in expected_ports}
    # Only the route check is under test here. The M2 worker probes also read /v1/models (to learn
    # the served model id) on their own ports, so match on the requests that carry no completion —
    # i.e. the bare route probes — rather than on every URL the tick touched.
    actual_urls = {
        part
        for request in requests
        if "chat/completions" not in request
        for part in request.split()
        if part.startswith("http://127.0.0.1:9")
    }
    assert expected_urls <= actual_urls, f"missing route probes: {expected_urls - actual_urls}"


@pytest.mark.parametrize(
    ("meter_ports", "expected_value"),
    [
        (None, "9002 9003 9004 9006"),
        ("9002 9003 9006", "9002 9003 9006"),
    ],
)
def test_installer_persists_meter_ports(
    tmp_path: Path,
    meter_ports: str | None,
    expected_value: str,
) -> None:
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text("#!/bin/sh\n[ \"$1\" != print ]\n")
    fake_launchctl.chmod(0o755)

    env = {
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    if meter_ports is not None:
        env["METER_PORTS"] = meter_ports

    subprocess.run(
        ["/bin/bash", str(INSTALLER), "m2-watchdog"],
        env=env,
        timeout=30,
        check=True,
        capture_output=True,
        text=True,
    )

    plist_path = home / "Library" / "LaunchAgents" / "com.localai.m2-watchdog.plist"
    with plist_path.open("rb") as plist_file:
        plist = plistlib.load(plist_file)
    assert plist["EnvironmentVariables"]["METER_PORTS"] == expected_value


@pytest.mark.parametrize("meter_ports", ["9002 & 9006", "9002\n9006"])
def test_installer_rejects_malformed_meter_ports(tmp_path: Path, meter_ports: str) -> None:
    plist_path = tmp_path / "home" / "Library" / "LaunchAgents" / "com.localai.m2-watchdog.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_text("existing plist")

    result = subprocess.run(
        ["/bin/bash", str(INSTALLER), "m2-watchdog"],
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "METER_PORTS": meter_ports,
        },
        timeout=30,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "space-separated list of port numbers" in result.stderr
    assert plist_path.read_text() == "existing plist"
