"""Release-closed costing arithmetic. No production imports or policy defaults."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

COMPONENTS = ('devex', 'capex', 'opex', 'finance', 'tax')

@dataclass(frozen=True)
class Row:
    period: str
    discount_factor: Decimal
    energy_mwh: Decimal
    costs_keur: tuple[Decimal, Decimal, Decimal, Decimal, Decimal]
    # Unique source line identities, one tuple per component. Never monetary guesses.
    origins: tuple[tuple[str, ...], ...]

    def __post_init__(self):
        if not isinstance(self.costs_keur, tuple) or not isinstance(self.origins, tuple) or any(not isinstance(x, tuple) for x in self.origins):
            raise ValueError('immutable tuples required')

@dataclass(frozen=True)
class Basis:
    metric: Literal['unlevered_pre_financing', 'levered_after_tax', 'lcos']
    convention: str | None
    rate_source: str | None
    currency: str
    energy_boundary: str
    charging: Literal['not_applicable', 'explicit_buy', 'net_spread']

@dataclass(frozen=True)
class Result:
    status: Literal['CANDIDATE', 'UNAVAILABLE']
    reason: str
    pv_energy_mwh: Decimal | None
    pv_components_keur: tuple[Decimal, ...] | None
    numerator_keur: Decimal | None
    components_eur_mwh: tuple[Decimal, ...] | None
    total_eur_mwh: Decimal | None


def calculate(rows: tuple[Row, ...], basis: Basis) -> Result:
    if not isinstance(rows, tuple):
        raise ValueError('immutable row tuple required')
    with localcontext() as context:
        context.prec = 50
        return _calculate(rows, basis)


def _calculate(rows: tuple[Row, ...], basis: Basis) -> Result:
    """Discount already aligned rows; never infer tax, debt or charging conventions.

    Caller must atomize every source amount into disjoint origins, including an
    explicit zero. Net-spread accounting cannot supply a gross LCOS buy-cost basis.
    Nominal/real/currency consistency belongs to the explicit convention receipt.
    """
    if basis.metric not in ('unlevered_pre_financing', 'levered_after_tax', 'lcos'):
        raise ValueError('unknown metric')
    if basis.currency != 'EUR' or not basis.energy_boundary:
        raise ValueError('requires EUR costs and explicit energy boundary')
    if basis.charging not in ('not_applicable', 'explicit_buy', 'net_spread'):
        raise ValueError('unknown charging basis')
    unavailable = lambda reason: Result('UNAVAILABLE', reason, None, None, None, None, None)
    if not basis.convention or not basis.rate_source:
        return unavailable('missing costing/finance convention or discount rate provenance')
    if basis.metric == 'lcos' and basis.charging != 'explicit_buy':
        return unavailable('LCOS requires explicit paid charging cost; net spread is not gross cost')
    if basis.metric != 'lcos' and basis.charging != 'not_applicable':
        raise ValueError('charging basis belongs to LCOS')
    seen_periods, seen_origins = set(), set()
    totals = [Decimal(0) for _ in COMPONENTS]
    energy = Decimal(0)
    for row in rows:
        if not row.period or row.period in seen_periods:
            raise ValueError('duplicate/missing aligned period')
        seen_periods.add(row.period)
        if len(row.costs_keur) != 5 or len(row.origins) != 5:
            raise ValueError('five attributed components required')
        for value in (row.discount_factor, row.energy_mwh, *row.costs_keur):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError('finite Decimal inputs required')
        if row.discount_factor <= 0 or row.energy_mwh < 0:
            raise ValueError('invalid discount factor or energy')
        if basis.metric == 'unlevered_pre_financing' and any(row.costs_keur[3:]):
            raise ValueError('unlevered pre-financing basis excludes finance and tax')
        for i, (amount, origins) in enumerate(zip(row.costs_keur, row.origins)):
            if not origins or any(not isinstance(o, str) or not o for o in origins):
                raise ValueError('every component, including zero, needs provenance')
            for origin in origins:
                if origin in seen_origins:
                    raise ValueError('source amount counted twice')
                seen_origins.add(origin)
            totals[i] += amount * row.discount_factor
        energy += row.energy_mwh * row.discount_factor
    if energy <= 0:
        return unavailable('no positive discounted delivered energy')
    numerator = sum(totals, Decimal(0))
    parts = tuple(x * 1000 / energy for x in totals)
    return Result('CANDIDATE', 'not approved for product use', energy, tuple(totals),
                  numerator, parts, numerator * 1000 / energy)
