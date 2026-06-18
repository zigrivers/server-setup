#!/usr/bin/env python3
"""Integration tests for scripts/rag-proxy.py against an in-process fake upstream.

No Qdrant / no MLX: the proxy's retrieval and collection-existence cache are stubbed. Verifies the
spec's test-plan items (a)-(f): verbatim pass-through incl. all fields, augmented body carries the
context + all fields, incremental SSE (no buffering), upstream-error passthrough, /v1/embeddings
never retrieves, and a freshly-created collection is seen on the next request.

Run: ~/ai/local-ai-stack/.venv/bin/python tests/test_rag_proxy.py
"""
from __future__ import annotations
import importlib.util
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def _load_proxy():
    spec = importlib.util.spec_from_file_location("rag_proxy", os.path.join(SCRIPTS, "rag-proxy.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- fake upstream ----------------
class FakeUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        fake_status = self.headers.get("x-fake-status")
        if fake_status:  # used to test upstream-error passthrough
            payload = json.dumps({"upstream_status": int(fake_status)}).encode()
            self.send_response(int(fake_status))
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        is_stream = False
        try:
            is_stream = bool(json.loads(body).get("stream"))
        except Exception:
            pass
        if is_stream:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(b'data: {"i":0}\n\n')
            self.wfile.flush()
            time.sleep(0.4)  # delay AFTER first chunk: proves the proxy didn't buffer
            self.wfile.write(b'data: {"i":1}\n\n')
            self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        # default: echo what we received so the test can inspect the forwarded body
        payload = json.dumps({"received": body.decode("utf-8", "replace"), "path": self.path}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _start_server(handler_cls):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# ---------------- harness ----------------
def setup():
    P = _load_proxy()
    up_srv, up_port = _start_server(FakeUpstream)
    P.DEFAULT_UPSTREAM = f"http://127.0.0.1:{up_port}"

    # stub the collection cache: a controllable set of "live" collections, no Qdrant
    live = {"names": {"mycoll"}}

    def fake_refresh():
        P._cache["names"] = set(live["names"])
        P._cache["ts"] = time.monotonic()
        P._cache["ever"] = True
        return P._cache["names"]

    P._refresh_collections = fake_refresh
    fake_refresh()

    # stub retrieval: returns a hit for any live collection (no embed/Qdrant)
    P._retrieve_with_timeout = lambda c, q: [{"score": 0.9, "text": f"CONTEXT for {c}", "path": "doc.md"}]

    prox_srv, prox_port = _start_server(P.Handler)
    base = f"http://127.0.0.1:{prox_port}"
    return P, base, live, up_srv, prox_srv


def test_passthrough_unknown_key_verbatim(base):
    body = {"model": "m", "temperature": 0.7, "stream_options": {"x": 1},
            "messages": [{"role": "user", "content": "hello"}]}
    r = httpx.post(f"{base}/v1/chat/completions", json=body,
                   headers={"authorization": "Bearer not-a-collection"}, timeout=10)
    assert r.status_code == 200, r.status_code
    assert r.headers.get("x-rag-applied") == "0", r.headers
    received = json.loads(json.loads(r.text)["received"])
    assert received == body, received  # forwarded byte-for-meaning, all fields intact


def test_augment_known_collection_preserves_fields(base):
    body = {"model": "m", "temperature": 0.7, "logprobs": True,
            "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "what is X?"}]}
    r = httpx.post(f"{base}/v1/chat/completions", json=body,
                   headers={"authorization": "Bearer mycoll"}, timeout=10)
    assert r.status_code == 200
    assert r.headers.get("x-rag-applied") == "1", r.headers
    assert r.headers.get("x-rag-hits") == "1"
    assert r.headers.get("x-rag-collection") == "mycoll"
    received = json.loads(json.loads(r.text)["received"])
    assert received["temperature"] == 0.7 and received["logprobs"] is True and received["model"] == "m"
    last_user = received["messages"][-1]["content"]
    assert "CONTEXT for mycoll" in last_user and "what is X?" in last_user
    assert received["messages"][0]["content"] == "sys"  # system untouched


def test_embeddings_never_retrieves(base):
    body = {"model": "m", "input": "text"}
    r = httpx.post(f"{base}/v1/embeddings", json=body,
                   headers={"authorization": "Bearer mycoll"}, timeout=10)
    assert r.status_code == 200
    assert r.headers.get("x-rag-applied") == "0", "embeddings must never be augmented"
    received = json.loads(json.loads(r.text)["received"])
    assert received == body


def test_upstream_error_passthrough(base):
    r = httpx.post(f"{base}/v1/chat/completions", json={"messages": []},
                   headers={"authorization": "Bearer mycoll", "x-fake-status": "503"}, timeout=10)
    assert r.status_code == 503, r.status_code
    assert json.loads(r.text)["upstream_status"] == 503


def test_streaming_is_incremental(base):
    t0 = time.monotonic()
    first_chunk_at = None
    chunks = []
    with httpx.stream("POST", f"{base}/v1/chat/completions",
                      json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
                      headers={"authorization": "Bearer not-a-collection"}, timeout=10) as r:
        for line in r.iter_lines():
            if not line:
                continue
            if first_chunk_at is None:
                first_chunk_at = time.monotonic() - t0
            chunks.append(line)
    # first chunk must arrive well before the upstream's 0.4s post-first-chunk delay completes
    assert first_chunk_at is not None and first_chunk_at < 0.35, f"first chunk too late: {first_chunk_at}"
    joined = "\n".join(chunks)
    assert '{"i":0}' in joined and '{"i":1}' in joined and "[DONE]" in joined, joined
    assert joined.index('{"i":0}') < joined.index('{"i":1}'), "SSE out of order"


def test_new_collection_seen_next_request(base, live):
    # 'fresh' is not live yet → no augmentation
    r1 = httpx.post(f"{base}/v1/chat/completions", json={"messages": [{"role": "user", "content": "q"}]},
                    headers={"authorization": "Bearer fresh"}, timeout=10)
    assert r1.headers.get("x-rag-applied") == "0"
    # simulate an ingest creating the collection
    live["names"].add("fresh")
    r2 = httpx.post(f"{base}/v1/chat/completions", json={"messages": [{"role": "user", "content": "q"}]},
                    headers={"authorization": "Bearer fresh"}, timeout=10)
    assert r2.headers.get("x-rag-applied") == "1", "freshly-created collection must be seen immediately"


def test_healthz(base):
    r = httpx.get(f"{base}/healthz", timeout=10)
    assert r.status_code == 200
    j = json.loads(r.text)
    assert j["service"] == "rag-proxy" and j["ok"] is True


if __name__ == "__main__":
    P, base, live, up_srv, prox_srv = setup()
    tests = [
        ("healthz", lambda: test_healthz(base)),
        ("passthrough_unknown_key_verbatim", lambda: test_passthrough_unknown_key_verbatim(base)),
        ("augment_known_collection_preserves_fields", lambda: test_augment_known_collection_preserves_fields(base)),
        ("embeddings_never_retrieves", lambda: test_embeddings_never_retrieves(base)),
        ("upstream_error_passthrough", lambda: test_upstream_error_passthrough(base)),
        ("streaming_is_incremental", lambda: test_streaming_is_incremental(base)),
        ("new_collection_seen_next_request", lambda: test_new_collection_seen_next_request(base, live)),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e!r}")
    print("ALL PASS" if not failed else f"{failed} FAILED")
    raise SystemExit(1 if failed else 0)
