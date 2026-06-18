#!/usr/bin/env python3
"""Retrieve context for a question and show the RAG-augmented prompt. Usage: rag-query.py '<q>'"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import rag_lib as R  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: rag-query.py '<question>'")
        sys.exit(1)
    q = sys.argv[1]
    cl = R.client()
    hits = R.retrieve(cl, q)
    print(f"retrieved {len(hits)} chunk(s) above gate {R.DEFAULT_MIN_SCORE} (top-k {R.DEFAULT_K}):")
    for h in hits:
        preview = h["text"][:80].replace("\n", " ")
        print(f"  [{h['score']:.3f}] {h['path']}: {preview}...")
    if not hits:
        print("  (nothing passed the gate — the query runs WITHOUT injected context, the safe default)")
    print("\n--- RAG-augmented prompt (first 600 chars) ---")
    print(R.build_rag_prompt(q, hits)[:600])


if __name__ == "__main__":
    main()
