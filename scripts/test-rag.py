#!/usr/bin/env python3
"""Unit tests for the pure RAG helpers (no model / no Qdrant needed)."""
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.dirname(__file__))
from rag_lib import (  # noqa: E402
    chunk, score_gate, dedup, build_rag_prompt, point_id,
    collection_config, pick_collection, maybe_augment,
    DEFAULT_MIN_SCORE, DEFAULT_K,
)

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

# ---------- proxy helpers ----------

def test_collection_config_defaults_when_absent():
    with tempfile.TemporaryDirectory() as d:
        cfg = collection_config("nope", config_dir=d)
        assert cfg == {"min_score": DEFAULT_MIN_SCORE, "top_k": DEFAULT_K}, cfg

def test_collection_config_reads_file():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "peptides.json"), "w").write(json.dumps({"min_score": 0.62, "top_k": 6}))
        cfg = collection_config("peptides", config_dir=d)
        assert cfg == {"min_score": 0.62, "top_k": 6}, cfg

def test_collection_config_malformed_falls_back():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "bad.json"), "w").write("{not json")
        cfg = collection_config("bad", config_dir=d)
        assert cfg == {"min_score": DEFAULT_MIN_SCORE, "top_k": DEFAULT_K}, cfg
        # partial config fills only provided keys
        open(os.path.join(d, "part.json"), "w").write(json.dumps({"min_score": 0.5}))
        cfg = collection_config("part", config_dir=d)
        assert cfg == {"min_score": 0.5, "top_k": DEFAULT_K}, cfg

def test_pick_collection_precedence():
    assert pick_collection({"x-rag-collection": "explicit", "authorization": "Bearer key"}) == "explicit"
    assert pick_collection({"authorization": "Bearer peptides"}) == "peptides"
    assert pick_collection({"Authorization": "bearer Peptides"}) == "Peptides"  # case-insensitive scheme
    assert pick_collection({}) is None
    assert pick_collection({"authorization": "Bearer "}) is None  # empty -> None
    assert pick_collection({"x-rag-collection": "  "}) is None  # whitespace -> None

def test_maybe_augment_no_collection_is_noop():
    body = {"model": "m", "messages": [{"role": "user", "content": "Q?"}]}
    out, applied, n, ms = maybe_augment(body, None, retrieve_fn=lambda c, q: (_ for _ in ()).throw(AssertionError("should not retrieve")))
    assert out is body and applied is False and n == 0

def test_maybe_augment_hit_replaces_last_user_and_preserves_fields():
    body = {"model": "m", "temperature": 0.2, "stream": True,
            "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "What is X?"}]}
    hits = [{"score": 0.9, "text": "X is a thing.", "path": "doc.md"}]
    out, applied, n, ms = maybe_augment(body, "coll", retrieve_fn=lambda c, q: hits)
    assert applied is True and n == 1
    assert out is not body and body["messages"][1]["content"] == "What is X?"  # original untouched
    assert out["temperature"] == 0.2 and out["stream"] is True and out["model"] == "m"  # fields preserved
    assert out["messages"][0]["content"] == "sys"  # system untouched
    assert "X is a thing." in out["messages"][1]["content"] and "What is X?" in out["messages"][1]["content"]

def test_maybe_augment_empty_hits_is_noop():
    body = {"messages": [{"role": "user", "content": "Q?"}]}
    out, applied, n, ms = maybe_augment(body, "coll", retrieve_fn=lambda c, q: [])
    assert out is body and applied is False and n == 0

def test_maybe_augment_retrieve_error_fails_open():
    body = {"messages": [{"role": "user", "content": "Q?"}]}
    out, applied, n, ms = maybe_augment(body, "coll", retrieve_fn=lambda c, q: 1 / 0)
    assert out is body and applied is False and n == 0

def test_maybe_augment_no_user_message_is_noop():
    body = {"messages": [{"role": "system", "content": "only system"}]}
    out, applied, n, ms = maybe_augment(body, "coll", retrieve_fn=lambda c, q: [{"score": 0.9, "text": "t", "path": "p"}])
    assert applied is False  # nothing to augment

if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok {name}")
    print("ALL PASS")
