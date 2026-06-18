# Constrained JSON via Outlines + MLX — Design Spec (F4)

**Status:** APPROVED for build (via /goal). Feature 4 of 6. Implementation home: **server-setup**
(serving tools). mlx_lm 0.31.3 has **no native structured output** (confirmed: no
`response_format`/`json_schema`/`grammar` flags), so any agent/tool step that needs parseable JSON
is currently relying on prompting luck. Outlines' MLX backend gives **schema-guaranteed** output.

## Goal
A local, offline way to generate JSON that is **guaranteed to satisfy a JSON Schema** — using
Outlines' grammar-constrained decoding over an MLX model — plus proof that it works where raw
prompting fails, and the integration pattern for using it in the stack.

## Non-goals (v1)
- Not a persistent always-on OpenAI-compatible structured endpoint — that's the documented
  *production* path; v1 proves the capability with a script to avoid standing up another always-on
  model in RAM amid the port/diverged-copy fragility we just hit in F2.
- Not rewiring existing agent steps yet (that follows once the capability is proven + a service is
  stood up).
- Not XGrammar (no XGrammar↔MLX integration exists, per the research).

## Approach
1. **Install** `outlines[mlxlm]` into the stack venv (`~/ai/local-ai-stack/.venv`). Verify it imports
   and that its MLX backend loads.
2. **Small demo model.** Download a small instruct model in MLX format (e.g. `mlx-community/
   Qwen2.5-1.5B-Instruct-4bit`, ~1GB) so the demo loads in seconds and proves the capability cheaply.
   (The production path uses the real 27–35B models; documented.)
3. **`scripts/structured-gen.py`**: load the model via `outlines.from_mlxlm(*mlx_lm.load(model))`,
   take a `--schema` (JSON Schema file) + `--prompt`, generate with the schema constraint, and print
   the JSON. Validate the output against the schema with `jsonschema` before printing (belt-and-
   suspenders) and exit non-zero if somehow invalid.
4. **Proof**: a demo that (a) runs constrained generation → schema-valid JSON every time, and (b)
   runs the SAME prompt as plain text (no constraint) and shows it can drift (extra prose, missing
   field) — i.e., the constraint is doing real work.
5. **Docs**: the integration pattern — how to wrap this as a persistent endpoint (a tiny server
   loading a real model once) and how a dashboard/agent step would call it for tool-call/extraction
   JSON. Note RAM cost and that the demo model ≠ production model.

## Files
| File | Change |
|---|---|
| `scripts/structured-gen.py` (new) | Outlines+MLX constrained JSON generator (model+schema+prompt → valid JSON) |
| `scripts/demo-structured-gen.sh` (new) | downloads the small model (once), runs constrained vs raw, shows the difference + schema validation |
| `schemas/example.schema.json` (new) | a sample schema (e.g. a "code review finding" object) to demo |
| `docs/constrained-json.md` (new) | the capability, how to run it, the production-endpoint pattern, RAM notes |
| `requirements` / venv | `outlines[mlxlm]` + `jsonschema` installed (document the pip line) |

## Error handling
- Outlines import/load failure → the script exits non-zero with a clear message (so we know the
  install is wrong before trusting it).
- Generated JSON failing `jsonschema` validation → exit non-zero (should never happen with the
  constraint; the check guards against a backend bug).
- Model download failure (offline / HF) → clear message; the script itself doesn't download (the
  demo script does, once).

## Test plan
- `python -c "import outlines"` succeeds in the venv.
- `structured-gen.py` with the example schema + a prompt → output parses as JSON AND validates
  against the schema.
- The raw-vs-constrained demo visibly differs (constrained always valid; raw may not be).
- M1 RAM headroom stays healthy (175GB free; a 1GB demo model is trivial).

## Revisions from multi-model review (incorporated) — and verified live
- **API confirmed empirically.** outlines **1.3.0** + mlx_lm **0.31.3**: `outlines.from_mlxlm(*mlx_lm.load(model))`
  (mlx_lm.load returns `(model, tokenizer)` — the unpack is correct), then
  `outlines.Generator(model, outlines.types.JsonSchema(schema))`. **Tested: produced schema-valid
  JSON from a 0.5B model.** Tokenizer is handled by `from_mlxlm` (no separate wiring).
- **Pinned versions** documented (`outlines==1.3.0`, mlx_lm 0.31.3); installed via `uv pip` (the venv
  is uv-managed and has no `pip`).
- **Schema-subset honesty:** the example schema is simple (object + enum + required + int); docs warn
  that deeply nested `anyOf`/`oneOf` may be unsupported — keep tool/extraction schemas simple.
- **Log raw on failure:** `structured-gen.py` prints the RAW output and exits non-zero if the
  belt-and-suspenders `jsonschema` validation ever fails (diagnosability).
- **Download idempotency:** the demo relies on HuggingFace's cache (first run downloads ~0.5B, later
  runs reuse it) — no custom flag needed.
- **Model existence verified:** `mlx-community/Qwen2.5-0.5B-Instruct-4bit` loads cleanly in MLX.
- **Constrained-vs-raw proof:** the raw 0.5B wrapped its (correct) JSON in ```` ```json ```` fences →
  `json.loads` fails; the constrained generator is valid by construction. The constraint does real work.

## Risks
- **Outlines ↔ mlx_lm 0.31.3 API drift** — `from_mlxlm` signature / API may differ by version; the
  build verifies the exact import path against the installed versions and pins what works.
- **Production RAM** — a persistent endpoint with a real 27–35B held in RAM is ~20–60GB; documented,
  not stood up in v1.
- **Scope honesty** — v1 proves the capability + pattern; it does not yet make any existing call
  schema-constrained. That wiring is a follow-up once a service exists.
