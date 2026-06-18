#!/usr/bin/env python3
"""
Generate JSON that is GUARANTEED to satisfy a JSON Schema, using Outlines' grammar-constrained
decoding over an MLX model. mlx_lm has no native structured output, so this fills that gap.

Usage:
  structured-gen.py --model <mlx-model-or-hf-id> --schema <schema.json> --prompt "<text>" [--max-tokens N]

Exit codes: 0 ok · 1 output failed schema validation (should not happen with the constraint) ·
2 import/load error. Pin: outlines==1.3.0 with mlx_lm 0.31.3.
"""
import argparse
import json
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--schema", required=True, help="path to a JSON Schema file")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--max-tokens", type=int, default=512)
    a = ap.parse_args()

    with open(a.schema) as f:
        schema = json.load(f)

    try:
        import mlx_lm
        import outlines
        from outlines.types import JsonSchema
        from jsonschema import validate
    except Exception as e:  # noqa: BLE001
        print(f"import error (is outlines[mlxlm]+jsonschema installed in this venv?): {e}", file=sys.stderr)
        sys.exit(2)

    try:
        model = outlines.from_mlxlm(*mlx_lm.load(a.model))
        generator = outlines.Generator(model, JsonSchema(schema))
    except Exception as e:  # noqa: BLE001
        print(f"load/generator error: {e}", file=sys.stderr)
        sys.exit(2)

    out = generator(a.prompt, max_tokens=a.max_tokens)

    try:
        obj = json.loads(out)
        validate(obj, schema)  # belt-and-suspenders; the constraint should already guarantee this
    except Exception as e:  # noqa: BLE001
        print(f"INVALID output (constraint failed): {e}\nRAW: {out!r}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(obj, indent=2))


if __name__ == "__main__":
    main()
