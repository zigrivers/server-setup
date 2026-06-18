#!/usr/bin/env python3
"""Ingest files/dirs into Qdrant for RAG. Re-ingesting a file replaces its old chunks (freshness via
stable id = hash(path+ord) + per-file delete).

Usage:
  rag-ingest.py <file-or-dir>...        # dirs are walked for a broad source-extension set
  rag-ingest.py --stdin                 # read newline-delimited file paths from stdin (one per line)
  rag-ingest.py --stdin --sync-paths    # after upserting, delete points whose source file is gone
                                        # (no-downtime whole-collection refresh; never empties it)

COLLECTION env selects the target collection (default server_setup)."""
import sys
import os
import glob
sys.path.insert(0, os.path.dirname(__file__))
import rag_lib as R  # noqa: E402
from qdrant_client.models import PointStruct  # noqa: E402

WALK_EXTS = ("*.md", "*.txt", "*.ts", "*.tsx", "*.js", "*.jsx", "*.py", "*.sh",
             "*.json", "*.yaml", "*.yml")


def collect_files(args: list[str]) -> list[str]:
    files: list[str] = []
    for p in args:
        if os.path.isdir(p):
            for ext in WALK_EXTS:
                files += glob.glob(os.path.join(p, "**", ext), recursive=True)
        elif os.path.isfile(p):
            files.append(p)
    return files


def main() -> None:
    argv = sys.argv[1:]
    sync = "--sync-paths" in argv
    use_stdin = "--stdin" in argv or "-" in argv
    paths = [a for a in argv if not a.startswith("-")]

    if use_stdin:
        files = [ln.strip() for ln in sys.stdin if ln.strip()]
    else:
        if not paths:
            print("usage: rag-ingest.py <file-or-dir>... | --stdin [--sync-paths]")
            sys.exit(1)
        files = collect_files(paths)

    files = sorted({f for f in files if os.path.isfile(f)})
    if not files:
        print("no matching files")
        sys.exit(1)

    cl = R.client()
    dim = len(R.embed(["probe"])[0])
    R.ensure_collection(cl, dim)
    ingested = 0
    current = set()
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
        pts = [PointStruct(id=R.point_id(f, i), vector=vecs[i],
                           payload={"path": f, "chunk": chunks[i], "ord": i}) for i in range(len(chunks))]
        cl.upsert(R.COLLECTION, pts)
        ingested += len(pts)
        current.add(f)
        print(f"  {f}: {len(pts)} chunks")

    removed_files = 0
    if sync:
        # delete points for files no longer present — no-downtime freshness (collection never emptied)
        stale = R.collection_paths(cl, R.COLLECTION) - current
        for pth in stale:
            R.delete_path(cl, pth)
            removed_files += 1
        if removed_files:
            print(f"  synced: removed {removed_files} vanished file(s)")

    print(f"ingested {ingested} chunks from {len(current)} files into collection "
          f"'{R.COLLECTION}' (dim {dim}){'; synced' if sync else ''}")


if __name__ == "__main__":
    main()
