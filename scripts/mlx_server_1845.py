#!/usr/bin/env python3
"""Run mlx_lm.server with the root-cause fix for mlx-lm #1845.

ArraysCache.advance() does `left_padding -= N` / `lengths -= N` lazily every decode step, and the
batched decode loop never evaluates cache state, so each linear-attention layer grows a graph one
node per step until Metal's 499,000 live-buffer cap kills the generation thread. The chain lives
on the batch's cache, so under steady concurrent load (the batch never drains) it accumulates
across requests: the orchestrator died every ~27 min during an 8-client enrichment run.

The fix is the one proposed in #1845's body: advance() adds N to a Python int, and the fields
fold it in on read. Same values, no per-step graph. Upstream declined the periodic-eval
workarounds (#1780, #1784, #1872) and has not merged this, so it is applied here at launch —
site-packages stays untouched and rollback is one line in start-orchestrator.sh.

Only the known leaking advance() is patched. A future mlx-lm that fixes or reshapes it is left
alone, with a line in the log saying so.

  python mlx_server_1845.py <mlx_lm.server arguments>
"""
import inspect
import sys
import textwrap

LEAKING_ADVANCE = """\
def advance(self, N):
    if self.lengths is not None:
        self.lengths -= N
    if self.left_padding is not None:
        self.left_padding -= N
"""
FIELDS = ("lengths", "left_padding")


def _field(name):
    raw, pending = f"_raw_{name}", f"_pending_{name}"

    def get(self):
        value, n = self.__dict__.get(raw), self.__dict__.get(pending, 0)
        if value is not None and n:
            value = value - n
            self.__dict__[raw], self.__dict__[pending] = value, 0
        return value

    def set(self, value):
        self.__dict__[raw], self.__dict__[pending] = value, 0

    return property(get, set)


def _advance(self, N):
    for name in FIELDS:
        if self.__dict__.get(f"_raw_{name}") is not None:
            key = f"_pending_{name}"
            self.__dict__[key] = self.__dict__.get(key, 0) + N


def patch(cls=None):
    """Patch ArraysCache (or cls) if its advance() is the known leaking one. True if patched."""
    if cls is None:
        from mlx_lm.models.cache import ArraysCache as cls
    try:
        source = textwrap.dedent(inspect.getsource(cls.advance))
    except (OSError, TypeError):
        return False
    if source != LEAKING_ADVANCE:
        return False
    for name in FIELDS:
        setattr(cls, name, _field(name))
    cls.advance = _advance
    return True


if __name__ == "__main__":
    if patch():
        print("mlx_server_1845: ArraysCache.advance patched (mlx-lm #1845)", file=sys.stderr, flush=True)
    else:
        print("mlx_server_1845: NOT patched — ArraysCache.advance is not the known leaking code",
              file=sys.stderr, flush=True)
    from mlx_lm.server import main

    sys.argv[0] = "mlx_lm.server"
    main()
