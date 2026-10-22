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
