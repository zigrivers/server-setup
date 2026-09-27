"""The #1845 launch shim for mlx_lm.server.

ArraysCache.advance() does `left_padding -= N` lazily every decode step and nothing evaluates it,
so each linear-attention layer holds a graph that grows one node per step until Metal's 499,000
live-buffer cap kills the generation thread. The shim folds steps into a Python int instead.

These must hold for the shim to be safe on the orchestrator: identical values, no per-step
array, and hands off anything that is not the known leaking code.

Run with the serving venv: ~/ai/local-ai-stack/.venv/bin/python -m pytest tests/test_mlx_server_1845.py
"""

import importlib.util
from pathlib import Path

import pytest

mx = pytest.importorskip("mlx.core")
from mlx_lm.models.cache import ArraysCache  # noqa: E402

SHIM = Path(__file__).resolve().parents[1] / "scripts" / "mlx_server_1845.py"
spec = importlib.util.spec_from_file_location("mlx_server_1845", SHIM)
shim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shim)
shim.patch()


def cache(left_padding=(5, 3), lengths=(10, 8)):
    c = ArraysCache(2, left_padding=list(left_padding))
    c.lengths = mx.array(lengths)
    return c


def test_advance_gives_the_same_values():
    c = cache()
    for _ in range(1000):
        c.advance(1)
    assert c.left_padding.tolist() == [5 - 1000, 3 - 1000]
    assert c.lengths.tolist() == [10 - 1000, 8 - 1000]


def test_advance_builds_no_array_per_step():
    # Unpatched, every advance() replaces left_padding with a new lazy array: that is the leak.
    c = cache()
    before = c._raw_left_padding
    for _ in range(1000):
        c.advance(1)
    assert c._raw_left_padding is before


def test_filter_extend_mask_finalize_match_plain_arithmetic():
    c = cache()
    c.advance(2)
    assert c.make_mask(6).tolist() == [[p >= lp for p in range(6)] for lp in (3, 1)]

    c.filter(mx.array([1]))
    assert c.left_padding.tolist() == [1] and c.lengths.tolist() == [6]

    other = cache(left_padding=(4,), lengths=(9,))
    other.advance(1)
    c.extend(other)
    assert c.left_padding.tolist() == [1, 3] and c.lengths.tolist() == [6, 8]

    c.finalize()
    c.advance(5)          # nothing pending may resurface once the fields are cleared
    assert c.left_padding is None and c.lengths is None


def test_patch_is_a_no_op_twice():
    assert shim.patch() is False


def test_unknown_advance_is_left_alone():
    class Other:
        def advance(self, N):
            self.x = N

    assert shim.patch(Other) is False
    assert "_raw_left_padding" not in vars(Other) and Other.advance.__name__ == "advance"
