#!/usr/bin/env bash
set -euo pipefail

# Demo: constrained (schema-guaranteed) vs raw (prompting only) JSON generation on the local stack.
# Downloads a tiny MLX model on first run (cached by HuggingFace afterward).
VENV="$HOME/ai/local-ai-stack/.venv"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${DEMO_MODEL:-mlx-community/Qwen2.5-0.5B-Instruct-4bit}"
SCHEMA="$REPO_DIR/schemas/example.schema.json"
PROMPT="Code review: line 42 calls eval() on user input. Return a finding with fields severity, summary, line."

echo "model: $MODEL"
echo "=== CONSTRAINED (Outlines + MLX — guaranteed to satisfy the schema) ==="
"$VENV/bin/python" "$REPO_DIR/scripts/structured-gen.py" --model "$MODEL" --schema "$SCHEMA" --prompt "$PROMPT" --max-tokens 200 2>/dev/null

echo
echo "=== RAW (plain prompting, no constraint — may include prose / invalid JSON) ==="
"$VENV/bin/python" - "$MODEL" "$PROMPT" 2>/dev/null <<'PY'
import sys, json, mlx_lm
model_id, prompt = sys.argv[1], sys.argv[2]
m, t = mlx_lm.load(model_id)
text = t.apply_chat_template([{"role": "user", "content": prompt + " Output only JSON."}], add_generation_prompt=True, tokenize=False)
out = mlx_lm.generate(m, t, text, max_tokens=200, verbose=False)
print(out)
try:
    json.loads(out)
    print("\n[raw output parses as JSON: YES]")
except Exception as e:
    print(f"\n[raw output parses as JSON: NO -> {e}]")
PY
echo
echo "Takeaway: the constrained generator is valid by construction; raw prompting is not guaranteed."
