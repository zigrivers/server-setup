#!/usr/bin/env python3
"""Calibrate a per-collection RAG gate. Probes the collection with a relevant query and an off-topic
query (gate disabled), reports the top score of each, suggests a `min_score` that separates them, and
writes RAG_CONFIG_DIR/<collection>.json so the proxy + eval arm gate alike.

Usage: rag-calibrate.py <collection> [relevant_query]
The off-topic probe is fixed (sourdough bread) — deliberately unrelated to any code project."""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(__file__))
import rag_lib as R  # noqa: E402

OFFTOPIC = "sourdough bread baking hydration oven temperature proofing time"


def top_score(cl, query: str, name: str) -> float:
    hits = R.retrieve(cl, query, k=4, min_score=0.0, name=name)  # gate off → see raw spread
    return round(max((h["score"] for h in hits), default=0.0), 3)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: rag-calibrate.py <collection> [relevant_query]")
        sys.exit(1)
    name = sys.argv[1]
    relevant = sys.argv[2] if len(sys.argv) > 2 else f"What is the {name} project and how is it structured?"
    cl = R.client()
    rel = top_score(cl, relevant, name)
    off = top_score(cl, OFFTOPIC, name)

    if rel > off:
        suggested = round((rel + off) / 2, 2)
        suggested = max(0.45, min(0.70, suggested))
        note = "ok"
    else:
        suggested = R.DEFAULT_MIN_SCORE
        note = "WEAK SEPARATION — relevant probe did not outscore off-topic; using default. Re-probe " \
               "with a more specific relevant query, or inspect the corpus."

    cfg_dir = R.RAG_CONFIG_DIR
    os.makedirs(cfg_dir, exist_ok=True)
    cfg_path = os.path.join(cfg_dir, f"{name}.json")
    json.dump({"min_score": suggested, "top_k": R.DEFAULT_K}, open(cfg_path, "w"))

    print(f"  calibration[{name}]: relevant_top={rel}  offtopic_top={off}  ->  min_score={suggested} ({note})")
    print(f"  wrote {cfg_path}")
    print(f"  tune later: edit that file (raise min_score to be stricter, lower to retrieve more).")


if __name__ == "__main__":
    main()
