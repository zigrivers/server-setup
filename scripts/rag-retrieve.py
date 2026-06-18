#!/usr/bin/env python3
"""Programmatic retrieval for the eval harness: given a query, print JSON with the RAG-augmented
prompt + the hits. Fail-soft: on any error, returns the query unchanged with n_hits=0.
Usage: rag-retrieve.py '<query>'"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(__file__))


def main() -> None:
    q = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        import rag_lib as R
        cl = R.client()
        cfg = R.collection_config(R.COLLECTION)  # match the proxy's per-collection gate
        hits = R.retrieve(cl, q, k=cfg["top_k"], min_score=cfg["min_score"], name=R.COLLECTION)
        print(json.dumps({
            "augmented": R.build_rag_prompt(q, hits),
            "n_hits": len(hits),
            "hits": [{"score": round(h["score"], 3), "path": h["path"]} for h in hits],
        }))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"augmented": q, "n_hits": 0, "error": str(e)}))


if __name__ == "__main__":
    main()
