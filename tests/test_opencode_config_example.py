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
            assert limit.get("output"), f"{provider}/{model_id} has no limit.output"


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
