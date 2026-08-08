import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "m2-watchdog.sh"
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
    actual_urls = {
        part
        for request in requests
        for part in request.split()
        if part.startswith("http://127.0.0.1:9")
    }
    assert actual_urls == expected_urls
