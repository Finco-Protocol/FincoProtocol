"""Minimal helpers for optional Streamlit imports.

These helpers let legacy UI modules stay importable in clean environments where
Streamlit is not installed, while still failing clearly if render functions are
called without the legacy UI dependency present.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


def get_streamlit() -> Any | None:
    """Return the Streamlit module when available, else ``None``."""
    try:
        return import_module("streamlit")
    except ModuleNotFoundError:
        return None


def require_streamlit(module_name: str):
    """Return Streamlit or raise a clear legacy-shell error."""
    st = get_streamlit()
    if st is None:
        raise RuntimeError(
            f"{module_name} requires the legacy Streamlit UI shell, but Streamlit "
            "is not installed in this environment."
        )
    return st
