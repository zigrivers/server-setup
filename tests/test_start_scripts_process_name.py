"""Role launchers: the oMLX default and the mlx_lm rollback path.

Default (2026-10-21): start-<role>.sh execs scripts/omlx-serve.sh. The watchdog finds a wedged
worker by its LISTENING PORT (lsof), so the process name no longer matters there; the dashboard
collector counts `omlx-server` and `mlx_lm.server` processes by name.

Rollback: LOCAL_AI_SERVER=mlx_lm execs start-<role>-mlx_lm.sh, which still launches the #1845 shim
under the `mlx_lm.server` name (exec -a) so the dashboard's process parser keeps seeing it.
"""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ROLES = ("orchestrator", "developer", "reviewer")


def exec_lines(script: Path) -> list[str]:
    return [line.strip() for line in script.read_text().splitlines() if line.strip().startswith("exec ")]


def test_every_role_launcher_defaults_to_omlx_and_can_roll_back():
    for role in ROLES:
        launcher = SCRIPTS / f"start-{role}.sh"
        text = launcher.read_text()
        assert 'LOCAL_AI_SERVER:-omlx' in text, launcher.name
        assert f'exec "$HERE/start-{role}-mlx_lm.sh"' in text, launcher.name
        assert exec_lines(launcher)[-1] == 'exec "$HERE/omlx-serve.sh"', launcher.name
        assert f"export ROLE={role}" in text, launcher.name


def test_omlx_serve_binds_role_port_and_key():
    text = (SCRIPTS / "omlx-serve.sh").read_text()
    last = exec_lines(SCRIPTS / "omlx-serve.sh")[-1]
    assert last.startswith('exec "$OMLX_BIN" serve')
    for flag in ("--model-dir", "--host", "--port", "--api-key", "--headless", "--no-hf-cache"):
        assert flag in text, flag
    # One symlink per role directory, so a role can never load a neighbour's weights.
    assert 'find "$MODEL_DIR" -maxdepth 1 -type l -delete' in text


def test_mlx_lm_rollback_launchers_keep_the_mlx_lm_server_name():
    shimmed = [s for s in SCRIPTS.glob("start-*-mlx_lm.sh") if "mlx_server_1845" in s.read_text()]
    assert {s.name for s in shimmed} == {f"start-{r}-mlx_lm.sh" for r in ROLES}
    for script in shimmed:
        assert exec_lines(script)[-1].startswith('exec -a mlx_lm.server python "$SHIM"'), script.name


def test_watchdog_kills_by_listening_port_not_process_name():
    text = (SCRIPTS / "m2-watchdog.sh").read_text()
    assert re.search(r"lsof -ti tcp:\$1 -sTCP:LISTEN", text)
    assert "pkill -f 'mlx_lm[.]server" not in text
