"""Request-local safeguarded Anderson proposals; no financial acceptance rules."""
from __future__ import annotations

from dataclasses import dataclass
import math


class ProposalRefused(ValueError):
    """Non-finite state or exhausted proposal budget; not a financial decision."""


@dataclass(frozen=True)
class JointSettings:
    maximum_iterations: int = 15
    accelerate: bool = True
    depth: int = 2
    terminal_switch: float = 1e-4

    def __post_init__(self):
        if type(self.maximum_iterations) is not int or not 1 <= self.maximum_iterations <= 50:
            raise ValueError("V9_INVALID_ITERATION_BUDGET")
        if type(self.accelerate) is not bool or type(self.depth) is not int or not 1 <= self.depth <= 3:
            raise ValueError("V9_INVALID_ACCELERATION_SETTINGS")
        if not math.isfinite(self.terminal_switch) or self.terminal_switch <= 0:
            raise ValueError("V9_INVALID_TERMINAL_SWITCH")


class Anderson:
    def __init__(self, settings: JointSettings):
        self.settings = settings
        self.previous = None
        self.previous_residual = math.inf
        self.history = []
        self.terminal = False
        self.accepted = 0
        self.refused = 0

    def step(self, mapped):
        mapped = tuple(float(v) for v in mapped)
        if len(mapped) != 6 or any(not math.isfinite(v) or v < 0 for v in mapped):
            raise ProposalRefused("V9_NONFINITE_OR_NEGATIVE_STATE")
        if self.previous is None:
            self.previous = mapped
            return mapped, True
        residual = max(abs(g - x) for g, x in zip(mapped, self.previous, strict=True))
        self.terminal = self.terminal or residual <= self.settings.terminal_switch
        attempt = self.settings.accelerate and not self.terminal
        if attempt and residual > .5 * self.previous_residual and self.history:
            self.history.clear()
            self.refused += 1
            attempt = False
        self.history.append((self.previous, mapped))
        self.history = self.history[-(self.settings.depth + 1):]
        self.previous_residual = residual
        candidate = self._extrapolate() if attempt and len(self.history) >= 2 else None
        plain = True
        if candidate is not None:
            bounded = all(math.isfinite(v) and v >= 0 for v in candidate)
            bounded = bounded and max(abs(v - g) for v, g in zip(candidate, mapped, strict=True)) <= 10 * max(1., residual)
            if bounded:
                mapped, plain = candidate, False
                self.accepted += 1
            else:
                self.refused += 1
                self.history.clear()
        self.previous = mapped
        return mapped, plain

    def _extrapolate(self):
        import numpy as np
        x = np.asarray([row[0] for row in self.history], dtype=float)
        g = np.asarray([row[1] for row in self.history], dtype=float)
        f = g - x
        df, dg = np.diff(f, axis=0).T, np.diff(g, axis=0).T
        if not np.all(np.isfinite(df)) or not np.any(df):
            return None
        try:
            gamma, _, _, _ = np.linalg.lstsq(df, f[-1], rcond=None)
        except np.linalg.LinAlgError:
            self.refused += 1
            return None
        return tuple(float(v) for v in g[-1] - dg @ gamma)
