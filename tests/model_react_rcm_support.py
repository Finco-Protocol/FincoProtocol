"""RC-M shared fixture for the React acceptance bodies (not collected by pytest).

The acceptance bodies are imported by ``tests/test_model_workspace_consolidation_browser.py`` — the existing mandatory Chromium
role — so no collection-time skip lives in any RC-M module.  The flag is read per request inside the live server, so it is
switched on for exactly the test that asks for it and restored afterwards.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def rcm_react_flag():
    old = os.environ.get("FINCO_MODEL_REACT_V1")
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    yield
    if old is None:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)
    else:
        os.environ["FINCO_MODEL_REACT_V1"] = old
