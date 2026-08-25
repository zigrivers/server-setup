"""The OpenCode plugin that turns a silent failed turn into a notification.

When a local mlx endpoint wedges, OpenCode retries three times and then the turn simply ends with
nothing on screen. On 2026-08-25 between 00:00 and 04:00 every local turn failed — 40 of 40 — and
the only symptom was the session going quiet. This plugin is the thing that speaks up, so its
behaviour is worth pinning: it must fire on a real error, stay quiet otherwise, not spam during an
outage, and never throw inside a session that is already failing.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "configs" / "opencode" / "plugins" / "local-stall-alert.mjs"

# Drives the plugin with a fake `$` that records commands instead of running them, then prints one
# JSON line describing what happened.
HARNESS = """
import(process.argv[1]).then(async (mod) => {
  const calls = [];
  const $ = (strings, ...vals) => {
    calls.push(String.raw({ raw: strings }, ...vals));
    return { quiet: async () => {} };
  };
  const hooks = await mod.LocalStallAlert({ $ });
  const events = JSON.parse(process.argv[2]);
  const threw = [];
  for (const event of events) {
    try { await hooks.event({ event }); } catch (e) { threw.push(String(e)); }
  }
  console.log(JSON.stringify({ calls, threw }));
});
"""


def drive(events: list[dict]) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    out = subprocess.run(
        [node, "--input-type=module", "-e", HARNESS, str(PLUGIN), json.dumps(events)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


ERROR = {"type": "session.error",
         "properties": {"error": {"data": {"message": "AI_RetryError: Failed after 3 attempts. Last error: Bad Gateway"}}}}


def test_notifies_when_a_turn_fails() -> None:
    result = drive([ERROR])
    assert len(result["calls"]) == 1
    assert "Bad Gateway" in result["calls"][0], "the operator needs the actual reason, not just 'failed'"
    assert not result["threw"]


def test_stays_quiet_on_ordinary_events() -> None:
    """session.idle fires constantly; a notification per idle turn would train the user to ignore it."""
    result = drive([{"type": "session.idle"}, {"type": "message.updated"}, {"type": "todo.updated"}])
    assert result["calls"] == []


def test_does_not_spam_during_an_outage() -> None:
    """An outage raises session.error on every retry — the operator needs one alert, not forty."""
    result = drive([ERROR, ERROR, ERROR, ERROR])
    assert len(result["calls"]) == 1


def test_survives_a_malformed_error_payload() -> None:
    """A plugin that throws here takes down a session that is already having a bad time."""
    result = drive([{"type": "session.error"},
                    {"type": "session.error", "properties": {}},
                    {"type": "session.error", "properties": {"error": "plain string"}}])
    assert not result["threw"]
