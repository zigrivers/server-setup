#!/usr/bin/env python3
"""Ingest files/dirs into Qdrant for RAG. Re-ingesting a file replaces its old chunks (freshness).
Usage: rag-ingest.py <file-or-dir>...  (dirs are walked for .md/.sh/.py/.txt)"""
import sys
import os
import glob
sys.path.insert(0, os.path.dirname(__file__))
import rag_lib as R  # noqa: E402
from qdrant_client.models import PointStruct  # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("usage: rag-ingest.py <file-or-dir>...")
        sys.exit(1)
    files: list[str] = []
    for p in args:
        if os.path.isdir(p):
            for ext in ("*.md", "*.sh", "*.py", "*.txt"):
                files += glob.glob(os.path.join(p, "**", ext), recursive=True)
        elif os.path.isfile(p):
            files.append(p)
    files = sorted(set(files))
    if not files:
        print("no matching files")
        sys.exit(1)

    cl = R.client()
    dim = len(R.embed(["probe"])[0])
    R.ensure_collection(cl, dim)
    total = 0
    for f in files:
        try:
            text = open(f, errors="ignore").read()
        except Exception:
            continue
        chunks = R.chunk(text)
        if not chunks:
            continue
        R.delete_path(cl, f)
        vecs = R.embed(chunks)
        pts = [PointStruct(id=R.point_id(f, i), vector=vecs[i], payload={"path": f, "chunk": chunks[i], "ord": i}) for i in range(len(chunks))]
        cl.upsert(R.COLLECTION, pts)
        total += len(pts)
        print(f"  {f}: {len(pts)} chunks")
    print(f"ingested {total} chunks from {len(files)} files into collection '{R.COLLECTION}' (dim {dim})")


if __name__ == "__main__":
    main()
