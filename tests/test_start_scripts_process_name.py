"""Servers launched through the #1845 shim must still look like mlx_lm.server in `ps`.

m2-watchdog kills a wedged worker with `pkill -f 'mlx_lm[.]server.*--port N'`, and the dashboard's
parseMlxProcesses keeps only ps lines containing `mlx_lm.server`. A bare `exec python shim.py`
matches neither: the watchdog's kill silently does nothing and the model drops off the dashboard.
"""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WATCHDOG_PATTERN = re.compile(r"mlx_lm[.]server.*--port 8002")   # as in m2-watchdog.sh


def exec_line(script: Path) -> str:
    return next(line for line in script.read_text().splitlines() if line.startswith("exec "))


def test_every_shimmed_launcher_keeps_the_mlx_lm_server_name():
    shimmed = [s for s in SCRIPTS.glob("start-*.sh") if "mlx_server_1845" in s.read_text()]
    assert {s.name for s in shimmed} >= {"start-orchestrator.sh", "start-developer.sh", "start-reviewer.sh"}
    for script in shimmed:
        assert exec_line(script).startswith('exec -a mlx_lm.server python "$SHIM"'), script.name


def test_watchdog_pattern_matches_the_renamed_process():
    # `exec -a NAME prog args` makes ps show NAME as argv[0], followed by the real arguments.
    ps_args = "mlx_lm.server /Users/admin/ai/local-ai-stack/scripts/mlx_server_1845.py --model m --port 8002"
    assert WATCHDOG_PATTERN.search(ps_args)
    assert not WATCHDOG_PATTERN.search("python /x/scripts/mlx_server_1845.py --model m --port 8002")
