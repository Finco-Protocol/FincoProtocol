"""Installed-package asset path resolver.

Resolves templates and static assets from their installed locations
(site-packages) rather than relative to a source checkout directory.
Used by main_web.py as a path resolver in clean-install mode.
"""
import os


def _installed_static_dir() -> str | None:
    """Return the directory of the installed `static` package, or None."""
    try:
        import static as _static_pkg
        return os.path.dirname(os.path.abspath(_static_pkg.__file__))
    except ImportError:
        return None


def resolve_static_dir(source_base_dir: str) -> str | None:
    """
    Return the static assets directory to mount, preferring the
    source-checkout path when it exists (dev mode), falling back to the
    installed `static` package (clean-install mode).
    """
    source_static = os.path.join(source_base_dir, "static")
    if os.path.isdir(source_static):
        return source_static
    return _installed_static_dir()
