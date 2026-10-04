"""Pure-domain adapter: legacy RevenueConfig → equivalent RevenuePlan.

Preparation for the later Model V2 runtime bridge. This adapter is a pure
function of the legacy revenue configuration — no canonical input contracts,
adapters, factories or persistence are touched, and no production runtime
path changes.

Representable legacy semantics (documented limitations are fail-closed):

- PPA (share of production)                    → PPA primary stream
- Merchant                                     → MERCHANT residual stream
                                                 (legacy residual = 1 − PPA
                                                 share; the V2 residual is
                                                 computed from the group)
- CfD (ANY enabled configuration)              → NOT representable — fails
                                                 closed. The legacy CfD settles
                                                 on a FIXED annual MWh volume
                                                 (cfd_volume_mwh_annual), where
                                                 0 is interpreted by the legacy
                                                 authority as UNLIMITED volume,
                                                 while a RevenuePlan overlay
                                                 settles on a generation-
                                                 RELATIVE share. The two
                                                 semantics are not numerically
                                                 equivalent, so no enabled
                                                 legacy CfD is convertible
                                                 without changing legacy
                                                 economics. Model the intended
                                                 CfD explicitly as a RevenuePlan
                                                 overlay instead.
- Fixed FiT alone                              → FIT_FIXED primary (share 1.0)
- Premium FiT                                  → FIT_PREMIUM settlement
                                                 overlay (share 1.0) with the
                                                 legacy merchant config as the
                                                 reference market authority
- Fixed FiT stacked with PPA / multiple tariff
  contracts on full generation                 → NOT representable (the
                                                 legacy aggregation would
                                                 double-count the same MWh) —
                                                 fails closed

The adapter is deterministic: identical input → identical plan.
"""
from __future__ import annotations

import dataclasses

from domain.revenue.plan import (
    RevenuePlan,
    RevenueStream,
    RevenueStreamType,
)
from domain.revenue.revenue_config import RevenueConfig


def revenue_plan_from_legacy_config(config: RevenueConfig) -> RevenuePlan:
    """Build the equivalent RevenuePlan for a legacy RevenueConfig.

    Raises ValueError (fail closed) for legacy combinations whose aggregation
    semantics cannot be represented without double counting.
    """
    streams: list[RevenueStream] = []
    has_primary_full_generation = False

    ppa = config.ppa
    if ppa is not None and ppa.ppa_enabled:
        if ppa.ppa_volume_share >= 1.0:
            has_primary_full_generation = True
        streams.append(RevenueStream(
            stream_id="ppa",
            stream_type=RevenueStreamType.PPA,
            name=ppa.ppa_counterparty or "Legacy PPA",
            start_year=ppa.ppa_start_year,
            term_years=ppa.ppa_term_years if ppa.ppa_term_years > 0 else None,
            volume_share=float(ppa.ppa_volume_share),
            ppa=ppa,
            counterparty=ppa.ppa_counterparty,
        ))

    merchant = config.merchant
    if merchant is not None and merchant.merchant_enabled:
        streams.append(RevenueStream(
            stream_id="merchant",
            stream_type=RevenueStreamType.MERCHANT,
            name="Legacy merchant tail",
            volume_share=None,  # residual of the generation group
            merchant=merchant,
        ))

    fit = config.fit
    if fit is not None and fit.fit_enabled:
        if fit.fit_type == "fixed_fit":
            if has_primary_full_generation or (
                ppa is not None and ppa.ppa_enabled
            ):
                raise ValueError(
                    "LEGACY_REVENUE_STACKING_NOT_REPRESENTABLE: a legacy fixed "
                    "FiT prices the FULL generation while a PPA is also active; "
                    "representing both as primary streams would double-count "
                    "the same MWh. Model the intended structure explicitly as "
                    "a RevenuePlan instead."
                )
            if merchant is not None and merchant.merchant_enabled:
                raise ValueError(
                    "LEGACY_REVENUE_STACKING_NOT_REPRESENTABLE: a legacy fixed "
                    "FiT prices the FULL generation while merchant revenue also "
                    "prices the FULL generation; the same MWh would be "
                    "monetized twice. Model the intended structure explicitly "
                    "as a RevenuePlan instead."
                )
            streams.append(RevenueStream(
                stream_id="fit_fixed",
                stream_type=RevenueStreamType.FIT_FIXED,
                name=fit.fit_scheme or "Legacy fixed FiT",
                start_year=1,
                term_years=fit.fit_term_years if fit.fit_term_years > 0 else None,
                volume_share=1.0,
                fit=fit,
            ))
        elif fit.fit_type == "premium":
            # The legacy aggregation adds supported-price revenue on the FULL
            # generation ON TOP of the merchant's full-generation market sale,
            # which double-counts the spot component of the supported volume.
            # The V2 premium overlay adds only the support payment, so the
            # legacy combination is NOT numerically equivalent. Fail closed —
            # the runtime bridge may later define an explicit migration policy.
            raise ValueError(
                "LEGACY_PREMIUM_NOT_EQUIVALENT: the legacy aggregation prices the "
                "supported volume at spot + premium ON TOP of the market sale, "
                "while the RevenuePlan premium overlay adds only the support "
                "payment. Represent the intended structure explicitly as a "
                "RevenuePlan instead of silently reinterpreting legacy economics."
            )
        else:
            raise ValueError(
                f"LEGACY_FIT_TYPE_UNSUPPORTED: {fit.fit_type!r} has no RevenuePlan "
                "representation in this adapter"
            )

    cfd = config.cfd
    if cfd is not None and cfd.cfd_enabled:
        # Fail closed for EVERY enabled legacy CfD. The legacy settlement
        # authority interprets cfd_volume_mwh_annual == 0 as UNLIMITED volume
        # and a positive value as a FIXED annual MWh volume; a RevenuePlan
        # overlay settles on a generation-RELATIVE share. No legacy CfD
        # configuration is numerically equivalent to a plan overlay without
        # reinterpreting legacy semantics, which this adapter must never do
        # (exact representation or fail closed — the runtime bridge may later
        # define an explicit migration policy).
        raise ValueError(
            "LEGACY_CFD_NOT_REPRESENTABLE: the legacy CfD settles on a fixed or "
            "unlimited annual MWh volume (cfd_volume_mwh_annual="
            f"{cfd.cfd_volume_mwh_annual!r}), while a RevenuePlan overlay settles "
            "on a generation-relative volume_share; the semantics are not "
            "numerically equivalent, so the adapter refuses to convert it "
            "silently. Model the intended CfD explicitly as a RevenuePlan overlay."
        )

    if config.capacity_market is not None and config.capacity_market.capacity_market_enabled:
        raise ValueError(
            "LEGACY_CAPACITY_MARKET_RESERVED: capacity market revenue is reserved "
            "vocabulary in this domain layer (Storage roadmap)"
        )
    if config.bess_revenue is not None and any((
        config.bess_revenue.arbitrage_enabled,
        config.bess_revenue.fcr_enabled,
        config.bess_revenue.afrr_enabled,
        config.bess_revenue.reactive_power_enabled,
        config.bess_revenue.capacity_firming_enabled,
    )):
        raise ValueError(
            "LEGACY_BESS_REVENUE_RESERVED: BESS revenue composition is reserved "
            "vocabulary in this domain layer; Storage remains fail-closed"
        )

    return RevenuePlan.create(
        streams=tuple(streams),
        market_price=merchant,
    )
