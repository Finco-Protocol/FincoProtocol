from dataclasses import dataclass
from decimal import Decimal
from .schema import ComponentState, ScenarioState, YieldObservation

@dataclass(frozen=True)
class YieldDecomposition:
    state: ComponentState
    gross_apy: Decimal | None
    organic_share: Decimal | None
    reward_dependency: Decimal | None
    reward_off_apy: Decimal | None

@dataclass(frozen=True)
class ScenarioResult:
    name: str
    state: ScenarioState
    apy: Decimal | None
    note: str

def decompose(obs: YieldObservation, tolerance: Decimal = Decimal("0.0001")) -> YieldDecomposition:
    total = obs.apy_total
    parts = (obs.apy_base, obs.apy_rewards, obs.apy_intrinsic)
    if total is None:
        return YieldDecomposition(ComponentState.COMPONENTS_UNAVAILABLE, None, None, None, None)
    if any(v is None for v in parts):
        return YieldDecomposition(ComponentState.COMPONENTS_UNAVAILABLE, total, None, None, None)
    base, rewards, intrinsic = parts
    if abs((base + rewards + intrinsic) - total) > tolerance:
        return YieldDecomposition(ComponentState.COMPONENT_MISMATCH, total, None, None, None)
    organic = Decimal("0") if total == 0 else (base + intrinsic) / total
    dependency = Decimal("0") if total == 0 else rewards / total
    reward_off = None if obs.annualized_costs is None else base + intrinsic - obs.annualized_costs
    return YieldDecomposition(ComponentState.AVAILABLE, total, organic, dependency, reward_off)

def run_scenario(name: str, obs: YieldObservation, *, shock_cost_apy: Decimal | None = None) -> ScenarioResult:
    name = name.upper()
    if name in {"REWARDS_OFF", "REWARDS_MINUS_50"}:
        if obs.apy_base is None or obs.apy_rewards is None or obs.apy_intrinsic is None:
            return ScenarioResult(name, ScenarioState.NOT_MODELLED, None, "APY components unavailable")
        reward = Decimal("0") if name == "REWARDS_OFF" else obs.apy_rewards / Decimal("2")
        return ScenarioResult(name, ScenarioState.MODELLED, obs.apy_base + obs.apy_intrinsic + reward, "transparent component shock")
    if name in {"EXIT_STRESS", "GAS_SHOCK"}:
        if obs.apy_total is None or shock_cost_apy is None:
            return ScenarioResult(name, ScenarioState.NOT_MODELLED, None, "explicit annualized cost shock required")
        return ScenarioResult(name, ScenarioState.MODELLED, obs.apy_total - shock_cost_apy, "user-supplied cost sensitivity")
    return ScenarioResult(name, ScenarioState.NOT_MODELLED, None, "unsupported scenario")
