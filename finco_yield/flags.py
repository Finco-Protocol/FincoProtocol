import os

_TRUE = {"1", "true", "yes", "on"}

def _env_flag(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in _TRUE

def yield_enabled() -> bool:
    return _env_flag("FINCO_YIELD_ENABLED")

def execution_enabled() -> bool:
    return _env_flag("FINCO_YIELD_EXECUTION_ENABLED")

def alert_automation_enabled() -> bool:
    """Background Yield alert evaluation is allowed to run (default OFF).

    This only states configuration.  It does not prove a scheduler is active.
    """
    return _env_flag("FINCO_YIELD_ALERT_AUTOMATION_ENABLED")
