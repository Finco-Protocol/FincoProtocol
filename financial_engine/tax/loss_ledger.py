"""financial_engine.tax.loss_ledger — Annual vintage FIFO loss-carryforward ledger.

Pure function.  No imports from app, finco_core or any framework.

One TaxAnnualLedgerEntry is produced per tax year.  Each entry carries
vintage-level detail (opening/generated/used/expired/closing per vintage).

Rules
-----
* Expiry before use: at the start of each tax year, expire vintages whose
  ``last_usable_tax_year < current_tax_year`` before applying them.
* FIFO: oldest vintage (smallest ``origin_tax_year``) is consumed first.
* One new vintage is created per loss-making tax year.
* A generated vintage has ``last_usable_tax_year = origin_tax_year + lcf_years``.
* No vintage amount may go negative.
* No income may be over-sheltered: ``taxable_after_lcf >= 0``.

Reconciliation identity per year::

    opening_loss_pre_expiry_keur
    + loss_generated_keur
    − loss_used_keur
    − loss_expired_keur
    == closing_loss_keur

And per vintage::

    closing_keur = opening_keur + generated_keur − used_keur − expired_keur
"""
from __future__ import annotations

from dataclasses import dataclass

from financial_engine.inputs import OpeningTaxLossVintageInput
from financial_engine.tax.models import TaxAnnualLedgerEntry, TaxLossVintage


@dataclass
class _VintageState:
    """Mutable internal vintage state threaded through the ledger."""
    vintage_id: str
    origin_tax_year: int
    last_usable_tax_year: int
    amount_keur: float
    source_label: str


def _opening_states_from_inputs(
    opening_inputs: tuple[OpeningTaxLossVintageInput, ...],
    loss_carryforward_years: int,
    first_tax_year: int | None = None,
) -> list[_VintageState]:
    """Build internal vintage states from opening inputs.

    Canonicalizes order by (origin_tax_year, stable_input_index) so FIFO
    consumption is deterministic and independent of caller tuple order.

    If first_tax_year is provided, every opening vintage must have
    origin_tax_year <= first_tax_year (fail-closed: TAX_OPENING_LOSS_FUTURE_VINTAGE).
    """
    states = []
    for i, v in enumerate(opening_inputs):
        if first_tax_year is not None and v.origin_tax_year > first_tax_year:
            raise ValueError(
                f"TAX_OPENING_LOSS_FUTURE_VINTAGE: opening vintage with "
                f"origin_tax_year={v.origin_tax_year} is later than the first modelled "
                f"tax year {first_tax_year}. A future-origin vintage cannot shelter "
                f"income in years before it was generated."
            )
        vid = v.source_label.strip() or f"opening_{v.origin_tax_year}_{i}"
        states.append(_VintageState(
            vintage_id=vid,
            origin_tax_year=v.origin_tax_year,
            last_usable_tax_year=v.origin_tax_year + loss_carryforward_years,
            amount_keur=v.amount_keur,
            source_label=v.source_label,
        ))
    # PR10_CORRECTION_A: Canonical FIFO ordering — sort by (origin_tax_year, stable_input_index).
    # Same-year vintages retain their relative input order.
    # Caller tuple order must NOT affect which vintage is consumed first.
    indexed = sorted(enumerate(states), key=lambda iv: (iv[1].origin_tax_year, iv[0]))
    return [s for _, s in indexed]


def _make_vintage_record(
    state: _VintageState,
    opening: float,
    generated: float,
    used: float,
    expired: float,
) -> TaxLossVintage:
    closing = max(0.0, opening + generated - used - expired)
    return TaxLossVintage(
        vintage_id=state.vintage_id,
        origin_tax_year=state.origin_tax_year,
        last_usable_tax_year=state.last_usable_tax_year,
        opening_keur=opening,
        generated_keur=generated,
        used_keur=used,
        expired_keur=expired,
        closing_keur=closing,
        source_label=state.source_label,
    )


def run_annual_fifo_ledger(
    taxable_income_before_lcf: tuple[float, ...],
    tax_year_indices: tuple[int, ...],
    opening_inputs: tuple[OpeningTaxLossVintageInput, ...],
    loss_carryforward_years: int,
    loss_use_allowed: tuple[bool, ...] | None = None,
) -> tuple[TaxAnnualLedgerEntry, ...]:
    """Run the annual FIFO loss ledger over all tax years.

    Parameters
    ----------
    taxable_income_before_lcf:
        One value per tax year (signed; negative = loss-making year).
    tax_year_indices:
        Calendar tax years corresponding to each entry (same length as above).
    opening_inputs:
        Pre-model opening loss vintages, oldest first.
    loss_carryforward_years:
        E.g. 5 for Generic Market A.

    Returns
    -------
    Tuple of TaxAnnualLedgerEntry, one per tax year, with full vintage detail.
    """
    if loss_use_allowed is not None and len(loss_use_allowed) != len(tax_year_indices):
        raise ValueError("loss_use_allowed must match tax_year_indices length")

    first_tax_year = tax_year_indices[0] if tax_year_indices else None
    pool = _opening_states_from_inputs(opening_inputs, loss_carryforward_years,
                                        first_tax_year=first_tax_year)
    entries: list[TaxAnnualLedgerEntry] = []

    for pos, (tax_year, taxable_before) in enumerate(
        zip(tax_year_indices, taxable_income_before_lcf)
    ):
        # ── 1. Snapshot of opening vintages (before expiry) ──────────────────
        opening_pre_expiry = sum(s.amount_keur for s in pool)

        # ── 2. Expire vintages whose window has closed ───────────────────────
        expired_records: list[TaxLossVintage] = []
        surviving: list[_VintageState] = []
        for s in pool:
            if s.last_usable_tax_year < tax_year:
                expired_records.append(_make_vintage_record(
                    s,
                    opening=s.amount_keur,
                    generated=0.0,
                    used=0.0,
                    expired=s.amount_keur,
                ))
            else:
                surviving.append(s)
        pool = surviving

        loss_expired = sum(r.expired_keur for r in expired_records)

        # ── 3a. Loss-making year: generate a new vintage ─────────────────────
        if taxable_before <= 0.0:
            generated_amount = -taxable_before if taxable_before < 0.0 else 0.0
            loss_used = 0.0
            taxable_after = 0.0

            new_id = f"gen_{tax_year}"
            new_state = _VintageState(
                vintage_id=new_id,
                origin_tax_year=tax_year,
                last_usable_tax_year=tax_year + loss_carryforward_years,
                amount_keur=generated_amount,
                source_label=f"generated_loss_{tax_year}",
            )

            # Build vintage records for this year
            opening_vints = tuple(
                _make_vintage_record(s, opening=s.amount_keur,
                                     generated=0.0, used=0.0, expired=0.0)
                for s in pool
            )
            used_vints: tuple[TaxLossVintage, ...] = ()

            if generated_amount > 1e-12:
                gen_rec = _make_vintage_record(
                    new_state,
                    opening=0.0,
                    generated=generated_amount,
                    used=0.0,
                    expired=0.0,
                )
                generated_vints = (gen_rec,)
                pool.append(new_state)
            else:
                generated_vints = ()

            closing_vints = tuple(
                _make_vintage_record(s, opening=s.amount_keur,
                                     generated=0.0, used=0.0, expired=0.0)
                for s in pool
            )

        # ── 3b. Profit year: consume oldest vintages (FIFO) ──────────────────
        else:
            if loss_use_allowed is not None and not loss_use_allowed[pos]:
                opening_vints = tuple(
                    _make_vintage_record(
                        s, opening=s.amount_keur, generated=0.0, used=0.0, expired=0.0
                    )
                    for s in pool
                )
                closing_vints = tuple(
                    _make_vintage_record(
                        s, opening=s.amount_keur, generated=0.0, used=0.0, expired=0.0
                    )
                    for s in pool
                )
                entries.append(
                    TaxAnnualLedgerEntry(
                        tax_year=tax_year,
                        opening_vintages=opening_vints,
                        expired_vintages=tuple(expired_records),
                        used_vintages=(),
                        generated_vintages=(),
                        closing_vintages=closing_vints,
                        opening_loss_pre_expiry_keur=opening_pre_expiry,
                        loss_expired_keur=loss_expired,
                        loss_used_keur=0.0,
                        loss_generated_keur=0.0,
                        closing_loss_keur=sum(s.amount_keur for s in pool),
                        taxable_income_before_lcf_keur=taxable_before,
                        taxable_income_after_lcf_keur=taxable_before,
                    )
                )
                continue

            remaining = taxable_before
            generated_amount = 0.0
            loss_used = 0.0
            used_pool: list[_VintageState] = []
            untouched_pool: list[_VintageState] = []

            for s in pool:
                if remaining <= 1e-12:
                    untouched_pool.append(s)
                    continue
                consume = min(s.amount_keur, remaining)
                loss_used += consume
                remaining -= consume
                residual = s.amount_keur - consume
                used_pool.append((s, consume, residual))

            taxable_after = max(0.0, remaining)

            # Rebuild pool (consumed vintages removed if fully used)
            new_pool: list[_VintageState] = []
            used_records: list[TaxLossVintage] = []
            opening_vints_list: list[TaxLossVintage] = []
            for s, consumed, residual in used_pool:
                opening_vints_list.append(
                    _make_vintage_record(s, opening=s.amount_keur,
                                         generated=0.0, used=consumed, expired=0.0)
                )
                used_records.append(
                    _make_vintage_record(s, opening=s.amount_keur,
                                         generated=0.0, used=consumed, expired=0.0)
                )
                if residual > 1e-12:
                    s.amount_keur = residual
                    new_pool.append(s)
            for s in untouched_pool:
                opening_vints_list.append(
                    _make_vintage_record(s, opening=s.amount_keur,
                                         generated=0.0, used=0.0, expired=0.0)
                )
                new_pool.append(s)

            pool = new_pool
            opening_vints = tuple(opening_vints_list)
            used_vints = tuple(used_records)
            generated_vints = ()
            closing_vints = tuple(
                _make_vintage_record(s, opening=s.amount_keur,
                                     generated=0.0, used=0.0, expired=0.0)
                for s in pool
            )

        closing_loss = sum(v.closing_keur for v in closing_vints)

        entries.append(TaxAnnualLedgerEntry(
            tax_year=tax_year,
            opening_vintages=opening_vints,
            expired_vintages=tuple(expired_records),
            used_vintages=used_vints,
            generated_vintages=generated_vints,
            closing_vintages=closing_vints,
            opening_loss_pre_expiry_keur=opening_pre_expiry,
            loss_expired_keur=loss_expired,
            loss_used_keur=loss_used,
            loss_generated_keur=generated_amount,
            closing_loss_keur=closing_loss,
            taxable_income_before_lcf_keur=taxable_before,
            taxable_income_after_lcf_keur=taxable_after,
        ))

    return tuple(entries)
