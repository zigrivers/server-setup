# Local Embeddings + Qdrant RAG (conservative)

Retrieve relevant chunks from your own docs/code to ground answers — **deliberately conservative**,
because the research is clear that *bad retrieval hurts more than no retrieval* (a single
answer-less-but-similar distractor can drop accuracy ~25%). So: small top-k, a relevance-score gate,
and **never inject context when nothing passes the gate**.

## Setup (one-time)
```
# Qdrant (Docker)
docker run -d --name qdrant-local -p 6333:6333 -v ~/ai/qdrant-storage:/qdrant/storage qdrant/qdrant
# Python deps in the stack venv
uv pip install --python ~/ai/local-ai-stack/.venv/bin/python qdrant-client mlx-embeddings
```
Embedder: `mlx-community/bge-small-en-v1.5-bf16` (384-dim). Verified locally: similar pairs ≈0.74,
unrelated ≈0.36 cosine — so the default gate **`RAG_MIN_SCORE=0.55`** cleanly separates them.

## Use
```
# Ingest (dirs are walked for .md/.sh/.py/.txt; re-ingesting a file replaces its old chunks)
~/ai/local-ai-stack/.venv/bin/python scripts/rag-ingest.py docs/ scripts/

# Query (shows each hit's score + the augmented prompt)
~/ai/local-ai-stack/.venv/bin/python scripts/rag-query.py "How do I enable prompt caching?"
```
Env knobs: `COLLECTION` (default `server_setup`), `RAG_TOP_K` (4), `RAG_MIN_SCORE` (0.55),
`RAG_EMBED_MODEL`, `QDRANT_URL`.

## How it's conservative
- **Top-k small** (4) and **score-gated** — hits below `RAG_MIN_SCORE` are dropped.
- **No noise injection** — if nothing passes the gate, the query runs unchanged.
- **Best chunk last** — kept chunks are ordered so the highest-score one sits adjacent to the
  question (mitigates "lost in the middle").
- **Freshness** — re-ingesting a file deletes its old chunks (stable id = hash(path+ord)).
- **L2-normalized** vectors; cosine distance in Qdrant.

## Measuring whether RAG helps (don't assume)
Adopt RAG for a use case **only if it measurably beats no-RAG**. Use the F1 eval harness: add an arm
that prepends `build_rag_prompt(query, retrieve(...))` and A/B it against baseline on a relevant
eval set. Keep it only where McNemar shows it doesn't regress.

## Production path
v1 loads the embedder per script run. For interactive use, a small persistent embedding endpoint
(model resident, OpenAI-style `/embeddings`) avoids reload latency. Qdrant is already persistent.
Tune `RAG_MIN_SCORE` per corpus from the scores `rag-query.py` prints.
