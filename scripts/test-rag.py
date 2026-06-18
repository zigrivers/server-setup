#!/usr/bin/env python3
"""Unit tests for the pure RAG helpers (no model / no Qdrant needed)."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from rag_lib import chunk, score_gate, dedup, build_rag_prompt, point_id  # noqa: E402

def test_chunk():
    text = "Block one.\n\n" + ("x" * 1000) + "\n\nBlock three."
    cs = chunk(text, size=300, overlap=50)
    assert len(cs) >= 3, cs
    assert all(len(c) <= 320 for c in cs), [len(c) for c in cs]  # ~size with small slack
    short = chunk("just one short block")
    assert short == ["just one short block"], short

def test_score_gate():
    hits = [{"score": 0.8, "text": "a"}, {"score": 0.4, "text": "b"}, {"score": 0.45, "text": "c"}]
    kept = score_gate(hits, 0.45)
    assert [h["text"] for h in kept] == ["a", "c"], kept

def test_dedup():
    hits = [{"text": "same"}, {"text": "same"}, {"text": "other"}]
    assert [h["text"] for h in dedup(hits)] == ["same", "other"]

def test_build_rag_prompt():
    assert build_rag_prompt("Q?", []) == "Q?"  # no hits -> unchanged, never inject noise
    p = build_rag_prompt("Q?", [{"score": 0.9, "text": "BEST", "path": "a"}, {"score": 0.5, "text": "WORSE", "path": "b"}])
    assert "Question: Q?" in p
    # best chunk (0.9) must appear AFTER the worse one (closer to the query)
    assert p.index("WORSE") < p.index("BEST"), p

def test_point_id_stable():
    assert point_id("a.md", 0) == point_id("a.md", 0)
    assert point_id("a.md", 0) != point_id("a.md", 1)

if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok {name}")
    print("ALL PASS")
