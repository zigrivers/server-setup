# Constrained JSON via Outlines + MLX

`mlx_lm` (0.31.3) has **no native structured output** — no `response_format`/`json_schema`/`grammar`
flags. So any agent/tool step that needs parseable JSON is, today, relying on prompting luck.
**Outlines'** grammar-constrained decoding over an MLX model makes the output **valid by
construction** against a JSON Schema.

## Install (one-time, in the stack venv)
```
uv pip install --python ~/ai/local-ai-stack/.venv/bin/python 'outlines[mlxlm]' jsonschema
```
Verified working: **outlines 1.3.0 + mlx_lm 0.31.3** (pin these). The MLX backend needs no PyTorch.

## Use
```
~/ai/local-ai-stack/.venv/bin/python scripts/structured-gen.py \
  --model mlx-community/Qwen2.5-0.5B-Instruct-4bit \
  --schema schemas/example.schema.json \
  --prompt "Code review: line 42 calls eval() on user input. Produce a finding."
```
Output is JSON guaranteed to satisfy the schema (it's also re-validated with `jsonschema` as a
belt-and-suspenders check; the script exits non-zero if validation ever fails). Run
`scripts/demo-structured-gen.sh` to see constrained vs raw side by side.

## Notes & limits
- **Schema subset.** Outlines supports common JSON Schema (objects, enums, required, types,
  arrays); deeply nested `anyOf`/`oneOf` may be unsupported — keep tool/extraction schemas simple.
- **Model.** The demo uses a tiny 0.5B model for speed (downloads once, HF-cached). The *production*
  path uses a real 27–35B model — see below.
- **max-tokens.** A too-small cap can truncate a large object; size it to the schema.

## Production path (when you wire this into the stack)
v1 is a CLI that loads a model per call (fine for batch/extraction, slow to reload). For interactive
use, stand up a **persistent** structured endpoint that loads a real model **once**:
- A small server process holding `outlines.from_mlxlm(*mlx_lm.load(<real-model>))` resident, exposing
  an OpenAI-compatible `response_format: {type:"json_schema", json_schema:{...}}` (or a simple
  `/structured` route). RAM cost ≈ the model's size (~20–60GB) held resident.
- Run it on a free port (mind the 8001–8003 collision with the `nibble` project — pick e.g. 8010),
  under launchd, with the hardened pre-flight pattern from `start-orchestrator.sh`.
- Dashboard/agent steps that need tool-call or extraction JSON then call it instead of hoping the
  base model emits valid JSON.
