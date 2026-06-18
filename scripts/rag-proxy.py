#!/usr/bin/env python3
"""Transparent, per-project, default-on-with-auto-skip RAG proxy.

An OpenAI-compatible proxy that sits IN FRONT of the meter (chain:
client -> rag-proxy:9200 -> meter:9002 -> worker). For POST /v1/chat/completions it resolves a Qdrant
collection from the request's `x-rag-collection` header (else the Bearer api-key), and IF that
collection exists AND a retrieved chunk clears the per-collection gate, it replaces the last user
message with a grounded prompt before forwarding. Otherwise — unknown key, no hits, or any retrieval
error — it forwards the request UNCHANGED. All other paths are pure pass-through. Streaming (SSE) is
forwarded incrementally via httpx so the first token is not delayed.

The pure logic (pick_collection / maybe_augment / collection_config) lives in rag_lib and is
unit-tested; this file is the HTTP glue + the existence cache + the timeout/lock guards.

Env: RAG_PROXY_HOST (127.0.0.1), RAG_PROXY_PORT (9200), RAG_PROXY_BRIDGE_HOST (optional 2nd bind),
UPSTREAM_BASE_URL (http://127.0.0.1:9002), RAG_TIMEOUT_MS (5000), RAG_CACHE_TTL_S (10),
plus rag_lib's QDRANT_URL / RAG_EMBED_MODEL / RAG_CONFIG_DIR.
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rag_lib as R  # noqa: E402
import httpx  # noqa: E402

HOST = os.environ.get("RAG_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("RAG_PROXY_PORT", "9200"))
BRIDGE_HOST = os.environ.get("RAG_PROXY_BRIDGE_HOST", "").strip()
RAG_TIMEOUT_S = float(os.environ.get("RAG_TIMEOUT_MS", "5000")) / 1000.0
CACHE_TTL_S = float(os.environ.get("RAG_CACHE_TTL_S", "10"))


def _normalize_upstream(base: str) -> str:
    """Treat UPSTREAM_BASE_URL as an origin; tolerate a trailing /v1 so we don't double it when the
    incoming path already starts with /v1 (e.g. http://127.0.0.1:9002/v1 -> http://127.0.0.1:9002)."""
    b = base.rstrip("/")
    if b.endswith("/v1"):
        b = b[:-3]
    return b


DEFAULT_UPSTREAM = _normalize_upstream(os.environ.get("UPSTREAM_BASE_URL", "http://127.0.0.1:9002"))

# Hop-by-hop headers never forwarded in either direction (RFC 7230 §6.1) + content framing we re-set.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade", "content-length", "content-encoding", "host",
}

# httpx client: generous/none read timeout so long generations stream; short connect so a dead
# upstream fails fast into a 502.
_HTTP = httpx.Client(timeout=httpx.Timeout(connect=5.0, read=None, write=60.0, pool=5.0))

# Retrieval (MLX embed + Qdrant) is serialized — MLX is not assumed thread-safe and the stack is
# single-user. A small pool lets us bound retrieval with a timeout without blocking the request thread.
_EMBED_LOCK = threading.Lock()
_RETRIEVE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-retrieve")

# --- collection existence cache: a name set with a short TTL; keep-last-known on error ---
_cache_lock = threading.Lock()
_cache = {"names": set(), "ts": 0.0, "ever": False}
_qclient = None


def _qdrant():
    global _qclient
    if _qclient is None:
        _qclient = R.client()
    return _qclient


def _refresh_collections() -> set:
    """Refresh the cached collection-name set from Qdrant. On error keep the last known-good set
    (a transient Qdrant blip must not silently disable RAG for every project)."""
    try:
        names = R.list_collections(_qdrant())
        with _cache_lock:
            _cache["names"] = names
            _cache["ts"] = time.monotonic()
            _cache["ever"] = True
        return names
    except Exception as e:  # noqa: BLE001
        log(f"cache-refresh-error {e!r} (keeping last-known {len(_cache['names'])})")
        with _cache_lock:
            _cache["ts"] = time.monotonic()  # avoid hammering a down Qdrant
        return _cache["names"]


def collection_is_live(name: str) -> bool:
    """True if `name` is an existing Qdrant collection. Uses the TTL cache, but a NEGATIVE result on a
    fresh cache still forces one refresh — so a just-ingested collection is visible immediately and
    there is no stale-negative window."""
    with _cache_lock:
        names, ts, ever = _cache["names"], _cache["ts"], _cache["ever"]
    fresh = ever and (time.monotonic() - ts) < CACHE_TTL_S
    if not fresh:
        names = _refresh_collections()
    if name in names:
        return True
    if fresh:  # cached set is fresh but missing the name → force one refresh (handles new ingests)
        names = _refresh_collections()
    return name in names


def _do_retrieve(collection: str, query: str):
    cfg = R.collection_config(collection)
    with _EMBED_LOCK:
        return R.retrieve(_qdrant(), query, k=cfg["top_k"], min_score=cfg["min_score"], name=collection)


def _retrieve_with_timeout(collection: str, query: str):
    """Run retrieval under RAG_TIMEOUT_S. On timeout/error raise so maybe_augment fails open."""
    fut = _RETRIEVE_POOL.submit(_do_retrieve, collection, query)
    return fut.result(timeout=RAG_TIMEOUT_S)


def log(msg: str) -> None:
    print(f"[rag-proxy] {time.strftime('%H:%M:%S')} {msg}", flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "rag-proxy/1.0"

    def log_message(self, *a):  # silence default noisy logging; we log our own line
        pass

    # ---- request entry points ----
    def do_GET(self):
        if self.path == "/healthz":
            return self._healthz()
        self._handle(b"")

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        self._handle(body)

    def do_DELETE(self):
        self._handle(b"")

    def do_PUT(self):
        length = int(self.headers.get("content-length") or 0)
        self._handle(self.rfile.read(length) if length else b"")

    # ---- core ----
    def _healthz(self):
        with _cache_lock:
            n = len(_cache["names"])
        payload = json.dumps({"service": "rag-proxy", "ok": True, "upstream": DEFAULT_UPSTREAM,
                              "collections": n}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def _handle(self, body: bytes):
        applied, n_hits, ms, collection = False, 0, 0, None
        # Only POST /v1/chat/completions is ever augmented; everything else is pure pass-through.
        if self.command == "POST" and self.path == "/v1/chat/completions":
            collection = R.pick_collection(dict(self.headers))
            if collection and collection_is_live(collection):
                try:
                    parsed = json.loads(body)
                    new_body, applied, n_hits, ms = R.maybe_augment(
                        parsed, collection, retrieve_fn=_retrieve_with_timeout)
                    if applied:
                        body = json.dumps(new_body).encode()
                except FutureTimeout:
                    log(f"retrieve-timeout collection={collection} (forwarding unchanged)")
                except json.JSONDecodeError:
                    pass  # unparseable → forward original bytes, let upstream judge (transparent)
                except Exception as e:  # noqa: BLE001 — fail-open
                    log(f"augment-error {e!r} (forwarding unchanged)")
        self._forward(body, collection, applied, n_hits, ms)

    def _upstream_target(self) -> str:
        override = (self.headers.get("x-rag-upstream") or "").strip()
        base = _normalize_upstream(override) if override else DEFAULT_UPSTREAM
        return base + self.path

    def _forward(self, body: bytes, collection, applied: bool, n_hits: int, ms: int):
        target = self._upstream_target()
        up_headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        up_headers["accept-encoding"] = "identity"  # don't let upstream gzip (we re-frame the body)
        up_headers["x-rag-applied"] = "1" if applied else "0"  # forwarded for future meter tagging
        want_stream = self._wants_stream(body)
        rag_headers = {
            "x-rag-collection": collection or "",
            "x-rag-applied": "1" if applied else "0",
            "x-rag-hits": str(n_hits),
            "x-rag-latency-ms": str(ms),
        }
        try:
            with _HTTP.stream(self.command, target, headers=up_headers, content=body) as resp:
                ct = resp.headers.get("content-type", "")
                streaming = want_stream or "text/event-stream" in ct
                self._send_status_and_headers(resp, rag_headers, streaming)
                if streaming:
                    self._pump_stream(resp)
                else:
                    data = resp.read()
                    try:
                        self.wfile.write(data)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            self._error(502, f"upstream unreachable: {e}")
            log(f"upstream-unreachable target={target} {e!r}")
            return
        except Exception as e:  # noqa: BLE001 — proxy/forward failure surfaces, never faked success
            self._error(502, f"proxy error: {e}")
            log(f"forward-error target={target} {e!r}")
            return
        log(f"{self.command} {self.path} collection={collection or '-'} applied={int(applied)} "
            f"hits={n_hits} rag_ms={ms} stream={int(want_stream)}")

    def _wants_stream(self, body: bytes) -> bool:
        if self.command != "POST" or not body:
            return False
        try:
            return bool(json.loads(body).get("stream"))
        except Exception:  # noqa: BLE001
            return b'"stream":true' in body.replace(b" ", b"")

    def _send_status_and_headers(self, resp, rag_headers, streaming: bool):
        self.send_response(resp.status_code)
        for k, v in resp.headers.items():
            if k.lower() in HOP_BY_HOP:
                continue
            self.send_header(k, v)
        for k, v in rag_headers.items():
            self.send_header(k, v)
        if streaming:
            self.send_header("connection", "close")  # EOF delimits the streamed body
        else:
            body_len = resp.headers.get("content-length")
            if body_len is not None:
                self.send_header("content-length", body_len)
            else:
                self.send_header("connection", "close")
        self.end_headers()

    def _pump_stream(self, resp):
        try:
            for chunk in resp.iter_raw():
                if not chunk:
                    continue
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    log("client-disconnect (closing upstream stream)")
                    resp.close()
                    return
        except httpx.HTTPError as e:
            log(f"stream-read-error {e!r}")

    def _error(self, code: int, msg: str):
        payload = json.dumps({"error": {"message": msg, "type": "rag_proxy_error"}}).encode()
        try:
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve():
    # Prime the cache so /healthz reports a real count and the first request is fast.
    _refresh_collections()
    servers = []
    binds = [HOST] + ([BRIDGE_HOST] if BRIDGE_HOST and BRIDGE_HOST != HOST else [])
    for h in binds:
        srv = Server((h, PORT), Handler)
        servers.append(srv)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        log(f"listening on http://{h}:{PORT}  upstream={DEFAULT_UPSTREAM}")
    log(f"collections cached: {len(_cache['names'])}  timeout={RAG_TIMEOUT_S}s  cache_ttl={CACHE_TTL_S}s")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    serve()
