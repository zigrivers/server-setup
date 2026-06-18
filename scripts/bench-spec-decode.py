#!/usr/bin/env python3
"""
Measure speculative-decoding throughput: generate the same prompt with and without a draft model
and report tok/s + speedup. Proves the win on a known-compatible (shared-tokenizer) pair.

Usage: bench-spec-decode.py <target-model> <draft-model> [num_draft_tokens] [max_tokens]
"""
import sys
import mlx_lm


def gen_tps(model, tok, prompt: str, max_tokens: int, draft=None, ndt: int = 3) -> tuple[float, int]:
    text = tok.apply_chat_template([{"role": "user", "content": prompt}], add_generation_prompt=True, tokenize=False)
    kwargs = {"max_tokens": max_tokens}
    if draft is not None:
        kwargs["draft_model"] = draft
        kwargs["num_draft_tokens"] = ndt
    last = None
    for r in mlx_lm.stream_generate(model, tok, text, **kwargs):
        last = r
    return (last.generation_tps, last.generation_tokens) if last else (0.0, 0)


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: bench-spec-decode.py <target> <draft> [num_draft_tokens] [max_tokens]")
        sys.exit(1)
    target_id, draft_id = sys.argv[1], sys.argv[2]
    ndt = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    max_tokens = int(sys.argv[4]) if len(sys.argv) > 4 else 256
    prompt = "Explain, in a few paragraphs, how a CPU cache hierarchy (L1/L2/L3) works and why it matters for performance."

    model, tok = mlx_lm.load(target_id)
    draft, _ = mlx_lm.load(draft_id)

    base_tps, base_n = gen_tps(model, tok, prompt, max_tokens, draft=None)
    spec_tps, spec_n = gen_tps(model, tok, prompt, max_tokens, draft=draft, ndt=ndt)

    print(f"target: {target_id}")
    print(f"draft:  {draft_id}  (num_draft_tokens={ndt})")
    print(f"baseline:    {base_tps:6.1f} tok/s  ({base_n} tokens)")
    print(f"speculative: {spec_tps:6.1f} tok/s  ({spec_n} tokens)")
    speedup = spec_tps / base_tps if base_tps else 0.0
    print(f"speedup:     {speedup:.2f}x" + ("  (draft helps)" if speedup > 1.05 else "  (no win — draft not accepted enough for this pair)"))


if __name__ == "__main__":
    main()
