import os

_TRUE = {"1", "true", "yes", "on"}

def _env_flag(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in _TRUE

def yield_enabled() -> bool:
    return _env_flag("FINCO_YIELD_ENABLED")

def execution_enabled() -> bool:
    return _env_flag("FINCO_YIELD_EXECUTION_ENABLED")
