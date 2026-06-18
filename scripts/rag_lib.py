"""
Conservative local RAG toolkit: embed (mlx-embeddings) → Qdrant → retrieve (small top-k + score
gate) → augment. The pure helpers (chunk / score_gate / dedup / build_rag_prompt) have no model or
Qdrant dependency and are unit-tested in test-rag.py. embed()/Qdrant calls are integration-verified.

Design rule (from research): bad retrieval hurts more than none — so we keep k small, gate by score,
and never inject context when nothing passes the gate.
"""
from __future__ import annotations
import hashlib
import json
import os
from typing import List, Dict, Any, Optional, Callable, Tuple

EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "mlx-community/bge-small-en-v1.5-bf16")
COLLECTION = os.environ.get("COLLECTION", "server_setup")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
DEFAULT_K = int(os.environ.get("RAG_TOP_K", "4"))
# Calibrated on live data: relevant chunks score ~0.72+, off-topic queries against this technical
# corpus floor around ~0.47 (higher than a totally-unrelated baseline). 0.55 cleanly separates them.
DEFAULT_MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.55"))
# Per-collection gate config lives here as <name>.json -> {"min_score": float, "top_k": int}. The
# ingester writes a calibrated value; the proxy and rag-retrieve.py both read it so they gate alike.
RAG_CONFIG_DIR = os.environ.get(
    "RAG_CONFIG_DIR", os.path.expanduser("~/ai/local-ai-stack/rag-collections"))

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


# ---------- proxy helpers (pure / unit-tested) ----------

def collection_config(name: str, config_dir: Optional[str] = None) -> Dict[str, Any]:
    """Per-collection gate config. Missing/malformed file → library defaults; a partial file fills
    only the keys it provides. Pure given `config_dir` (defaults to RAG_CONFIG_DIR)."""
    cfg = {"min_score": DEFAULT_MIN_SCORE, "top_k": DEFAULT_K}
    base = config_dir if config_dir is not None else RAG_CONFIG_DIR
    path = os.path.join(base, f"{name}.json")
    try:
        data = json.load(open(path))
        if isinstance(data, dict):
            if isinstance(data.get("min_score"), (int, float)):
                cfg["min_score"] = float(data["min_score"])
            if isinstance(data.get("top_k"), int):
                cfg["top_k"] = data["top_k"]
    except (OSError, ValueError):
        pass  # absent or malformed → defaults
    return cfg


def pick_collection(headers: Dict[str, str]) -> Optional[str]:
    """Resolve the target collection from request headers: `x-rag-collection` wins, else the Bearer
    api-key value. Header lookup is case-insensitive. Empty/whitespace → None (pure pass-through)."""
    h = {k.lower(): v for k, v in headers.items()}
    explicit = (h.get("x-rag-collection") or "").strip()
    if explicit:
        return explicit
    auth = (h.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        key = auth[7:].strip()
        if key:
            return key
    return None


def maybe_augment(
    body: Dict[str, Any],
    collection: Optional[str],
    retrieve_fn: Callable[[str, str], List[Dict[str, Any]]],
) -> Tuple[Dict[str, Any], bool, int, int]:
    """Ground a chat-completions body from `collection`. Returns (new_body, applied, n_hits, ms).

    `retrieve_fn(collection, query)` returns scored hits (the proxy supplies one that embeds+searches
    Qdrant under a timeout). Fail-open and non-mutating: no collection / no last-user-message / no
    hits / any retrieve error → returns the ORIGINAL body unchanged (applied=False). On hits, returns
    a copy with only the last user message's content replaced by build_rag_prompt(original, hits);
    every other field is preserved. `ms` is the retrieval time (for x-rag-latency-ms)."""
    import time
    if not collection:
        return body, False, 0, 0
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return body, False, 0, 0
    last_user = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
    if last_user is None:
        return body, False, 0, 0
    query = msgs[last_user].get("content", "")
    t0 = time.monotonic()
    try:
        hits = retrieve_fn(collection, query)
    except Exception:  # noqa: BLE001 — fail-open: retrieval must never break serving
        return body, False, 0, int((time.monotonic() - t0) * 1000)
    ms = int((time.monotonic() - t0) * 1000)
    if not hits:
        return body, False, 0, ms
    new_body = dict(body)
    new_msgs = [dict(m) for m in msgs]
    orig = new_msgs[last_user].get("content", "")
    new_msgs[last_user]["content"] = build_rag_prompt(orig, hits)
    new_body["messages"] = new_msgs
    return new_body, True, len(hits), ms


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


def list_collections(cl) -> set:
    """Set of existing Qdrant collection names (for the proxy's existence cache)."""
    return {c.name for c in cl.get_collections().collections}


def collection_exists(cl, name: str) -> bool:
    return name in list_collections(cl)


def delete_path(cl, path: str, name: str = COLLECTION):
    from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector
    cl.delete(name, points_selector=FilterSelector(filter=Filter(
        must=[FieldCondition(key="path", match=MatchValue(value=path))])))


def collection_paths(cl, name: str = COLLECTION) -> set:
    """Distinct `path` payload values currently stored in the collection (for no-downtime sync:
    delete points whose source file is gone)."""
    from qdrant_client.models import Filter
    paths, offset = set(), None
    while True:
        points, offset = cl.scroll(name, scroll_filter=Filter(must=[]), with_payload=True,
                                   with_vectors=False, limit=512, offset=offset)
        for p in points:
            pth = (p.payload or {}).get("path")
            if pth:
                paths.add(pth)
        if offset is None:
            break
    return paths


def retrieve(cl, query: str, k: int = DEFAULT_K, min_score: float = DEFAULT_MIN_SCORE, name: str = COLLECTION) -> List[Dict[str, Any]]:
    qv = embed([query])[0]
    res = cl.query_points(name, query=qv, limit=k, with_payload=True).points
    hits = [{"score": float(p.score), "text": p.payload.get("chunk", ""), "path": p.payload.get("path", "?")} for p in res]
    return dedup(score_gate(hits, min_score))
