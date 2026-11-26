"""FINCO45C (FINCO44-NEW-06 / C3-E-04): app.cache never initialises Streamlit caching outside a Streamlit runtime.

Streamlit is not a production dependency; a fake ``streamlit`` module records decorator construction so the tests are
deterministic. Values, clear() and the headless lru fallback are unchanged; inside a runtime Streamlit's cache is used.
"""
from __future__ import annotations

import importlib
import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class _FakeStreamlit(types.ModuleType):
    def __init__(self, runtime_exists: bool):
        super().__init__("streamlit")
        self.decorations = 0
        self.calls = 0
        rt = types.ModuleType("streamlit.runtime")
        rt.exists = lambda: runtime_exists
        self.runtime = rt

    def cache_data(self, *a, **k):
        self.decorations += 1
        outer = self

        def deco(func):
            store = {}

            def wrapped(*args, **kwargs):
                outer.calls += 1
                key = (args, tuple(sorted(kwargs.items())))
                if key not in store:
                    store[key] = func(*args, **kwargs)
                return store[key]

            wrapped.clear = store.clear
            return wrapped
        return deco


@pytest.fixture
def fake_streamlit(monkeypatch):
    def install(runtime_exists: bool):
        st = _FakeStreamlit(runtime_exists)
        monkeypatch.setitem(sys.modules, "streamlit", st)
        monkeypatch.setitem(sys.modules, "streamlit.runtime", st.runtime)
        return st
    return install


def _fresh_cache():
    import app.cache
    return importlib.reload(app.cache)


def test_import_outside_runtime_never_builds_a_streamlit_cache(fake_streamlit):
    st = fake_streamlit(runtime_exists=False)
    cache = _fresh_cache()
    assert st.decorations == 0                                  # import never decorates with Streamlit

    hits = []

    @cache.cache_data(show_spinner=False)
    def square(x):
        hits.append(x)
        return x * x

    assert square(3) == 9 and square(3) == 9 and hits == [3]   # headless lru fallback, same values
    assert st.decorations == 0 and st.calls == 0
    square.clear()
    assert square(3) == 9 and hits == [3, 3]


def test_unhashable_arguments_stay_uncached_and_correct(fake_streamlit):
    fake_streamlit(runtime_exists=False)
    cache = _fresh_cache()

    @cache.cache_data()
    def total(values):
        return sum(values)

    assert total([1, 2, 3]) == 6 and total([1, 2]) == 3


def test_inside_a_streamlit_runtime_the_streamlit_cache_is_used_lazily(fake_streamlit):
    st = fake_streamlit(runtime_exists=True)
    cache = _fresh_cache()
    assert st.decorations == 0                                  # still nothing at import

    @cache.cache_data(show_spinner=False)
    def double(x):
        return 2 * x

    assert st.decorations == 0
    assert double(4) == 8 and double(4) == 8
    assert st.decorations == 1 and st.calls == 2                # created once, on first in-runtime call
    double.clear()                                              # clears the Streamlit-side cache too
    assert double(4) == 8 and st.decorations == 1


def test_no_streamlit_installed_is_headless(monkeypatch):
    monkeypatch.delitem(sys.modules, "streamlit", raising=False)
    cache = _fresh_cache()
    assert cache._active_streamlit_runtime() is None
    cache.clear_all_caches()


def test_api_import_does_not_import_streamlit_or_log_runtime_warnings():
    code = ("import logging, sys; logging.basicConfig(level=logging.WARNING);"
            "import app.cache, utils.cache;"
            "print('streamlit' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "False"
    assert "No runtime found" not in out.stderr and "streamlit" not in out.stderr.lower()


@pytest.fixture(autouse=True)
def _restore_real_cache_module():
    yield
    sys.modules.pop("streamlit", None) if isinstance(sys.modules.get("streamlit"), _FakeStreamlit) else None
    import app.cache
    importlib.reload(app.cache)
    logging.getLogger().handlers  # noqa: B018 - no global logging change made
