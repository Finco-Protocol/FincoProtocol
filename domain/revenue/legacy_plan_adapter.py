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
- CfD with unlimited annual volume             → CfD settlement overlay
  (cfd_volume_mwh_annual == 0)                   (share 1.0 of eligible
                                                 generation)
- CfD with a fixed annual MWh volume           → NOT representable as a
                                                 volume share without
                                                 generation data — fails
                                                 closed
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
            reference_stream_id = "merchant" if (
                merchant is not None and merchant.merchant_enabled
            ) else None
            if reference_stream_id is None and merchant is None:
                raise ValueError(
                    "LEGACY_PREMIUM_REFERENCE_MARKET_REQUIRED: a legacy premium "
                    "FiT settles against the market price; provide the legacy "
                    "merchant configuration as the reference authority"
                )
            streams.append(RevenueStream(
                stream_id="fit_premium",
                stream_type=RevenueStreamType.FIT_PREMIUM,
                name=fit.fit_scheme or "Legacy premium support",
                start_year=1,
                term_years=fit.fit_term_years if fit.fit_term_years > 0 else None,
                volume_share=1.0,
                fit=fit,
                reference_stream_id=reference_stream_id,
            ))
        else:
            raise ValueError(
                f"LEGACY_FIT_TYPE_UNSUPPORTED: {fit.fit_type!r} has no RevenuePlan "
                "representation in this adapter"
            )

    cfd = config.cfd
    if cfd is not None and cfd.cfd_enabled:
        if cfd.cfd_volume_mwh_annual > 0.0:
            raise ValueError(
                "LEGACY_CFD_FIXED_VOLUME_NOT_SHARE_REPRESENTABLE: the legacy CfD "
                "declares a fixed annual MWh volume; a RevenuePlan overlay needs "
                "a generation-relative volume_share. Model the intended CfD "
                "share explicitly."
            )
        reference_stream_id = "merchant" if (
            merchant is not None and merchant.merchant_enabled
        ) else None
        if reference_stream_id is None and merchant is None:
            raise ValueError(
                "LEGACY_CFD_REFERENCE_MARKET_REQUIRED: a legacy CfD settles "
                "against the market price; provide the legacy merchant "
                "configuration as the reference authority"
            )
        streams.append(RevenueStream(
            stream_id="cfd",
            stream_type=RevenueStreamType.CFD,
            name=cfd.cfd_counterparty or "Legacy CfD",
            start_year=1,
            term_years=cfd.cfd_term_years if cfd.cfd_term_years > 0 else None,
            volume_share=1.0,
            cfd=cfd,
            reference_stream_id=reference_stream_id,
            counterparty=cfd.cfd_counterparty,
        ))

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
