"""Explicit async plugins shared by discovery, isolated probes and workers.

Use the plugins' own backend parametrization. In particular, never synthesize,
strip or alias AnyIO's original parameter IDs. Pytest rejects a missing plugin
at startup; there is no reduced-coverage fallback.
"""

PLUGINS = ("pytest_asyncio.plugin", "anyio.pytest_plugin")


def plugin_args():
    return [arg for plugin in PLUGINS for arg in ("-p", plugin)]


def loaded_plugins(config):
    """Observe actual registration, independent of the requested argument list."""
    names = {getattr(plugin, "__name__", None) for _, plugin in config.pluginmanager.list_name_plugin()}
    return [name for name in PLUGINS if name in names]


def all_plugin_registrations(config):
    """Actual registrations, including ambient plugins and local conftests."""
    import hashlib
    from pathlib import Path
    records = []
    for name, plugin in config.pluginmanager.list_name_plugin():
        if plugin is None:
            continue
        module = getattr(plugin, "__name__", None) or type(plugin).__module__
        filename = getattr(plugin, "__file__", None)
        records.append({"registration": str(name), "module": module,
                        "implementation": getattr(type(plugin), "__qualname__", ""),
                        "file_sha256": hashlib.sha256(Path(filename).read_bytes()).hexdigest()
                        if filename and Path(filename).is_file() else None})
    return sorted(records, key=lambda r: (r["registration"], r["module"]))


def semantic_plugin_profile(records):
    """Retain every plugin; normalize process addresses and conftest root paths."""
    result = []
    for item in records:
        label = item["registration"]
        if label.isdecimal():
            label = "<unnamed>"
        elif item["module"].endswith("conftest") and label.endswith("conftest.py"):
            label = "<conftest>"
        result.append({**item, "registration": label})
    return sorted(result, key=lambda r: (r["module"], r["implementation"], r["registration"], r["file_sha256"] or ""))
