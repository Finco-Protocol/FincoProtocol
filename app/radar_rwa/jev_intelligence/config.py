"""Environment configuration. Default OFF; the API key is read only when needed."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from .contracts import JevMode

ENABLED_ENV = "FINCO_JEV_INTELLIGENCE_ENABLED"
MODE_ENV = "FINCO_JEV_INTELLIGENCE_MODE"
MODEL_ENV = "FINCO_JEV_MODEL"
KEY_ENV = "TYPESAFE_API_KEY"
RATE_ENV = "FINCO_JEV_MAX_EVALUATIONS_PER_MINUTE"

DEFAULT_MODEL = "jev-latest"
DEFAULT_MAX_EVALUATIONS_PER_MINUTE = 30
_TRUTHY = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class JevIntelligenceConfig:
    mode: JevMode = JevMode.OFF
    model: str = DEFAULT_MODEL
    max_evaluations_per_minute: int = DEFAULT_MAX_EVALUATIONS_PER_MINUTE

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if isinstance(self.max_evaluations_per_minute, bool) or self.max_evaluations_per_minute < 1:
            raise ValueError("max_evaluations_per_minute must be a positive integer")

    @property
    def enabled(self) -> bool:
        return self.mode is not JevMode.OFF

    @property
    def visible(self) -> bool:
        return self.mode is JevMode.VISIBLE

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "JevIntelligenceConfig":
        env = os.environ if environ is None else environ
        if str(env.get(ENABLED_ENV, "0")).strip().lower() not in _TRUTHY:
            return cls()
        # Enabled without an explicit mode is SHADOW: never silently promoted to VISIBLE.
        raw = str(env.get(MODE_ENV, "SHADOW")).strip().upper()
        try:
            mode = JevMode(raw)
        except ValueError:
            return cls()  # unknown mode fails closed to OFF
        model = str(env.get(MODEL_ENV, DEFAULT_MODEL)).strip() or DEFAULT_MODEL
        try:
            rate = int(str(env.get(RATE_ENV, DEFAULT_MAX_EVALUATIONS_PER_MINUTE)))
        except ValueError:
            rate = DEFAULT_MAX_EVALUATIONS_PER_MINUTE
        return cls(mode=mode, model=model, max_evaluations_per_minute=max(1, rate))


def api_key(environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    key = str(env.get(KEY_ENV, "")).strip()
    return key or None
