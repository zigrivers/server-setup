"""The OpenCode provider template must not hand a new machine a stale model id or an uncapped context.

Two things this template got wrong before 2026-08-25.

1. It named models the stack no longer serves — the bf16 orchestrator and `llmfan46/Qwen3.6-27B`.
   `mlx_lm.server` treats the `model` field as an instruction to LOAD that model, not to select one,
   so a stale id here is how a Mac ends up holding two copies. Only the meter's per-port pins
   (METER_ORCH_MODEL and friends) masked it.

2. It set no `limit.context` on the local models, so OpenCode never compacted and sessions grew past
   170k tokens. mlx leaks Metal buffer descriptors while decoding, and longer prompts reach the
   499,000-buffer ceiling sooner: four orchestrator crashes in 90 minutes on 2026-08-24, then both
   M2 workers overnight.
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "configs" / "opencode" / "opencode.json.example"

LOCAL_PROVIDERS = ("local-orch", "local-dev", "local-review")
# Above roughly this size the orchestrator is slower than the developer endpoint AND is where it
# crashed. See docs/dev-stack-models.md for the measured crossover.
MAX_CONTEXT = 131_072
# OpenCode clamps max_tokens at 32000 on the wire regardless of a larger limit.output, and the
# orchestrator has been truncated at exactly that ceiling — so 32000 is both the floor and the cap.
EXPECTED_OUTPUT = 32_000


def config() -> dict:
    return json.loads(EXAMPLE.read_text())


def test_local_models_declare_a_context_cap() -> None:
    """Without a cap OpenCode never compacts, and the session grows until mlx dies."""
    for provider in LOCAL_PROVIDERS:
        models = config()["provider"][provider]["models"]
        for model_id, spec in models.items():
            limit = spec.get("limit", {})
            assert limit.get("context"), f"{provider}/{model_id} has no limit.context"
            assert limit["context"] <= MAX_CONTEXT, (
                f"{provider}/{model_id} allows {limit['context']} tokens, above the {MAX_CONTEXT} cap"
            )
            assert limit.get("output") == EXPECTED_OUTPUT, (
                f"{provider}/{model_id} caps output at {limit.get('output')}; the orchestrator has "
                f"produced {EXPECTED_OUTPUT}-token turns and gets cut off below that"
            )


def test_local_model_ids_are_paths_the_servers_actually_serve() -> None:
    """A bare Hugging Face repo id here is an instruction to download and load a second model."""
    for provider in LOCAL_PROVIDERS:
        for model_id in config()["provider"][provider]["models"]:
            assert model_id.startswith("/"), (
                f"{provider} names '{model_id}', which is not a local path — "
                "mlx would load it as a new model rather than use the resident one"
            )
            assert "qwen36" not in model_id.lower() or "orchestrator" in model_id.lower(), (
                f"{provider} still names a retired Qwen3.6 worker build: {model_id}"
            )
            assert "bf16" not in model_id, (
                f"{provider} names the bf16 orchestrator (65 GB); the stack serves mixed9"
            )


def test_compaction_is_configured() -> None:
    """A context cap only helps if OpenCode acts on it."""
    compaction = config().get("compaction", {})
    assert compaction.get("auto") is True, "auto-compaction must be on"
    # Thinking models routinely spend 12k tokens reasoning before the summary appears.
    assert compaction.get("reserved", 0) >= 12_000, "too little headroom reserved for the summary"


def test_review_provider_points_at_the_router() -> None:
    """:9006 is the review router (M2 reviewer, spilling to M1); :9003 is the reviewer alone."""
    url = config()["provider"]["local-review"]["options"]["baseURL"]
    assert "9006" in url, f"local-review should use the review router on :9006, got {url}"


def test_local_providers_set_their_own_timeouts() -> None:
    """A wedged endpoint must fail on a bounded clock, and a slow one must not be cut off early.

    Worst observed time-to-first-token on these endpoints is 209s, so a default chunk timeout in the
    tens of seconds would kill healthy turns; and OpenCode does not retry a chunk timeout at all
    (anomalyco/opencode#20466), so a killed turn is a stall the operator has to notice by hand.
    """
    for provider in LOCAL_PROVIDERS:
        options = config()["provider"][provider]["options"]
        assert options.get("timeout"), f"{provider} has no request timeout"
        assert options.get("chunkTimeout", 0) >= 210_000, (
            f"{provider} chunkTimeout is below the 209s worst-case first token seen on this stack"
        )


def test_instructions_do_not_duplicate_the_auto_loaded_agents_file() -> None:
    """~/.config/opencode/AGENTS.md is auto-loaded; naming it again sent every house rule twice."""
    instructions = config().get("instructions", [])
    assert not any("AGENTS.md" in str(i) for i in instructions), (
        "AGENTS.md is already auto-loaded from the OpenCode config dir; listing it in `instructions` "
        "put 12,555 duplicated characters in every single request"
    )


def test_the_stall_alert_plugin_is_wired_up() -> None:
    """Upstream failures end a turn silently; the plugin is the only thing that surfaces them."""
    assert any("local-stall-alert" in p for p in config().get("plugin", []))


def test_title_generation_does_not_go_to_a_paid_model() -> None:
    """21,734 title generations had been going to a cloud model."""
    assert config()["small_model"].startswith("local-")


def test_only_tool_disables_that_actually_work_are_kept() -> None:
    """Config should not carry patterns that were measured to do nothing.

    OpenCode's `tools` block reaches MCP tools by their server prefix. Its own built-in
    list_mcp_resources / list_mcp_resource_templates / read_mcp_resource are NOT reachable: `mcp*`,
    `*resource*` and `*mcp_resource*` were each sent through a recording endpoint and left all
    three in the tool list. Keeping such a pattern reads as coverage that does not exist.
    """
    tools = config().get("tools", {})
    dead = [k for k in tools if "resource" in k or k.startswith("mcp")]
    assert not dead, f"these patterns were measured to have no effect: {dead}"
    assert tools.get("local-ai-delegate_run_local_plan") is False
