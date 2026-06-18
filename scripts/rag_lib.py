"""
Conservative local RAG toolkit: embed (mlx-embeddings) → Qdrant → retrieve (small top-k + score
gate) → augment. The pure helpers (chunk / score_gate / dedup / build_rag_prompt) have no model or
Qdrant dependency and are unit-tested in test-rag.py. embed()/Qdrant calls are integration-verified.

Design rule (from research): bad retrieval hurts more than none — so we keep k small, gate by score,
and never inject context when nothing passes the gate.
"""
from __future__ import annotations
import hashlib
import os
from typing import List, Dict, Any

EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "mlx-community/bge-small-en-v1.5-bf16")
COLLECTION = os.environ.get("COLLECTION", "server_setup")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
DEFAULT_K = int(os.environ.get("RAG_TOP_K", "4"))
# Calibrated on live data: relevant chunks score ~0.72+, off-topic queries against this technical
# corpus floor around ~0.47 (higher than a totally-unrelated baseline). 0.55 cleanly separates them.
DEFAULT_MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.55"))

# ---------- pure helpers (unit-tested) ----------

def chunk(text: str, size: int = 800, overlap: int = 100) -> List[str]:
    """Block-aware chunking: pack blank-line-separated blocks up to `size` chars; carry `overlap`
    chars of tail context into the next chunk. Avoids slicing mid-block where possible."""
    blocks = [b for b in text.replace("\r\n", "\n").split("\n\n")]
    chunks: List[str] = []
    cur = ""
    for b in blocks:
        b = b.strip("\n")
        if not b:
            continue
        if cur and len(cur) + len(b) + 2 > size:
            chunks.append(cur.strip())
            cur = (cur[-overlap:] if overlap else "") + "\n\n" + b
        else:
            cur = (cur + "\n\n" + b) if cur else b
        # a single oversized block: hard-split it
        while len(cur) > size:
            chunks.append(cur[:size].strip())
            cur = cur[size - overlap:]
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if c.strip()]


def score_gate(hits: List[Dict[str, Any]], min_score: float) -> List[Dict[str, Any]]:
    """Keep only hits at/above the relevance gate. Each hit: {score, text, path}."""
    return [h for h in hits if h.get("score", 0.0) >= min_score]


def dedup(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop exact-duplicate chunk texts (overlap can surface near-identical neighbors)."""
    seen = set()
    out = []
    for h in hits:
        key = h.get("text", "").strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def build_rag_prompt(query: str, hits: List[Dict[str, Any]]) -> str:
    """Augment the query with retrieved context. No hits → return the query unchanged (never inject
    noise). Otherwise sort by score ASC so the best chunk sits LAST, adjacent to the query."""
    if not hits:
        return query
    ordered = sorted(hits, key=lambda h: h.get("score", 0.0))  # best last (nearest the query)
    ctx = "\n\n".join(f"[{h.get('path', '?')}]\n{h['text']}" for h in ordered)
    return (
        "Use the following context to answer, but only if it is relevant; if it is not, answer from "
        f"your own knowledge.\n\n--- context ---\n{ctx}\n--- end context ---\n\nQuestion: {query}"
    )


def point_id(path: str, ord_: int) -> int:
    """Stable 63-bit id from path+ord so re-ingest overwrites instead of duplicating."""
    h = hashlib.sha1(f"{path}#{ord_}".encode()).hexdigest()
    return int(h[:15], 16)


# ---------- model + Qdrant (integration) ----------

_model = None
_tok = None
def _embedder():
    global _model, _tok
    if _model is None:
        import mlx_embeddings
        from mlx_embeddings.utils import load
        _model, _tok = load(EMBED_MODEL)
    return _model, _tok


def embed(texts: List[str]) -> List[List[float]]:
    """Embed + L2-normalize."""
    import numpy as np
    import mlx_embeddings
    model, tok = _embedder()
    out = mlx_embeddings.generate(model, tok, texts)
    arr = np.array(out.text_embeds if hasattr(out, "text_embeds") else out, dtype="float32")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).tolist()


def client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL)


def ensure_collection(cl, dim: int, name: str = COLLECTION):
    from qdrant_client.models import Distance, VectorParams
    existing = {c.name for c in cl.get_collections().collections}
    if name not in existing:
        cl.create_collection(name, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))


def delete_path(cl, path: str, name: str = COLLECTION):
    from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector
    cl.delete(name, points_selector=FilterSelector(filter=Filter(
        must=[FieldCondition(key="path", match=MatchValue(value=path))])))


def retrieve(cl, query: str, k: int = DEFAULT_K, min_score: float = DEFAULT_MIN_SCORE, name: str = COLLECTION) -> List[Dict[str, Any]]:
    qv = embed([query])[0]
    res = cl.query_points(name, query=qv, limit=k, with_payload=True).points
    hits = [{"score": float(p.score), "text": p.payload.get("chunk", ""), "path": p.payload.get("path", "?")} for p in res]
    return dedup(score_gate(hits, min_score))
