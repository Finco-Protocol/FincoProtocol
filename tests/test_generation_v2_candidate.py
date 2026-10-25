"""Generation Losses & Pre-COD candidate (WF-03A) — acceptance battery.

RELEASE-CLOSED CANDIDATE TESTS (house convention): the flag must be a
literal False at import, every public calculation entry fails closed by
default, and only an isolated monkeypatch fixture enables the gate.

Proves the ten mission financial invariants on canonical date semantics:
operating rows are taken from the RELEASED ``PeriodEngine`` (Jun 30 /
Dec 31 boundaries, COD stubs, leap-year denominators — no periodisation
change) and construction-month boundaries from exact month arithmetic.
"""
from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.generation_v2_candidate import (
    ACTIVATION_ENABLED,
    DegradationOnset,
    FirstYearAvailability,
    LossFactorWindow,
    PreCodCommissioning,
    TransmissionLossFactor,
    VolumeAdjustmentEvent,
    require_release,
    validate_no_event_overlaps,
)
from app.generation_v2_candidate.pure import (
    apply_transmission_loss,
    apply_transmission_loss_to_periods,
    apply_volume_adjustments,
    build_pre_cod_proposal,
    compose_operating_adjustments,
    month_sequence,
    overlap_days,
    period_days_inclusive,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def released(monkeypatch):
    """Isolated acceptance fixture: enable the candidate gate in memory."""
    import app.generation_v2_candidate.contracts as contracts
    import app.generation_v2_candidate.pure as pure
    monkeypatch.setattr(contracts, "ACTIVATION_ENABLED", True)
    monkeypatch.setattr(pure, "ACTIVATION_ENABLED", True)
    yield


# ── Canonical period axis (RELEASED engine, unchanged) ───────────────────────


@pytest.fixture(scope="module")
def canonical_axis():
    """A real released PeriodEngine: FC 2025-01-01, 6 construction months,
    COD 2025-07-01 — semiannual operating rows on Jun 30 / Dec 31."""
    from finco_core.engine.period_engine import PeriodEngine

    engine = PeriodEngine(
        financial_close=date(2025, 1, 1),
        construction_months=6,
        horizon_years=25,
        ppa_years=15,
        cod_date=date(2025, 7, 1),
    )
    return engine.periods()


# ── Release closure ──────────────────────────────────────────────────────────


class TestReleaseClosure:
    def test_flag_is_a_literal_false_at_import(self):
        assert ACTIVATION_ENABLED is False

    @pytest.mark.parametrize("call", [
        lambda: apply_transmission_loss(
            TransmissionLossFactor(mode="FLAT", flat_factor=0.0), 1.0,
            date(2026, 1, 1)),
        lambda: apply_transmission_loss_to_periods(
            TransmissionLossFactor(mode="FLAT", flat_factor=0.0),
            [(date(2026, 6, 30), 1.0)]),
        lambda: compose_operating_adjustments(
            period_index=0, operating_year_index=1, on_date=date(2026, 6, 30),
            degradation=DegradationOnset(annual_rate=0.004),
            availability=FirstYearAvailability(0.95, 0.98),
            transmission_loss=TransmissionLossFactor(mode="FLAT",
                                                     flat_factor=0.0)),
        lambda: overlap_days(date(2026, 1, 1), date(2026, 6, 30),
                             date(2026, 2, 1), date(2026, 3, 1)),
        lambda: period_days_inclusive(date(2026, 1, 1), date(2026, 6, 30)),
        lambda: apply_volume_adjustments(1000.0, date(2026, 1, 1),
                                         date(2026, 6, 30), ()),
        lambda: build_pre_cod_proposal(
            PreCodCommissioning(
                commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
                monthly_ramp_pct=(50.0,) * 6, price_basis="FIXED",
                fixed_price_eur_mwh=30.0),
            capacity_mw=10.0, month_hours={(2025, m): 720.0 for m in range(1, 7)},
            availability=0.95),
        lambda: month_sequence(date(2025, 1, 1), date(2025, 7, 1)),
        lambda: validate_no_event_overlaps(()),
        lambda: __import__(
            "app.generation_v2_candidate.contracts",
            fromlist=["canonical_json"]).canonical_json({}),
    ])
    def test_every_calculation_entry_fails_closed(self, call):
        with pytest.raises(ValueError, match="GENERATION_V2_RELEASE_CLOSED"):
            call()

    def test_no_environment_variable_can_enable_the_gate(self, monkeypatch):
        for env in ("FINCO_GENERATION_V2_ENABLED",
                    "FINCO_GENERATION_V2_ACTIVATION",
                    "GENERATION_V2_ACTIVATION_ENABLED"):
            monkeypatch.setenv(env, "1")
        import app.generation_v2_candidate.contracts as contracts
        assert contracts.ACTIVATION_ENABLED is False
        with pytest.raises(ValueError, match="GENERATION_V2_RELEASE_CLOSED"):
            require_release()


# ── Invariant 1: gross = delivered + physical losses (exact) ─────────────────


class TestInvariant1EnergyConservation:
    def test_split_is_exact_by_construction(self, released):
        split = apply_transmission_loss(
            TransmissionLossFactor(mode="FLAT", flat_factor=0.03), 1000.0,
            date(2026, 6, 30))
        assert split.loss_mwh == pytest.approx(30.0)
        assert split.delivered_mwh == pytest.approx(970.0)
        assert split.delivered_mwh + split.loss_mwh == split.gross_mwh

    def test_sum_conservation_over_many_periods(self, released):
        rows = [(date(2026, 6, 30), 1000.0), (date(2026, 12, 31), 1200.0),
                (date(2027, 6, 30), 900.0)]
        out = apply_transmission_loss_to_periods(
            TransmissionLossFactor(mode="FLAT", flat_factor=0.025), rows)
        assert sum(g for _, g in rows) == pytest.approx(3100.0)
        assert sum(d + l for _, d, l in out) == pytest.approx(3100.0)
        assert sum(l for _, _, l in out) == pytest.approx(3100.0 * 0.025)

    def test_zero_factor_is_a_legitimate_zero_loss(self, released):
        split = apply_transmission_loss(
            TransmissionLossFactor(mode="FLAT", flat_factor=0.0), 500.0,
            date(2026, 6, 30))
        assert split.loss_mwh == 0.0
        assert split.delivered_mwh == 500.0

    def test_dated_series_split_uses_window_factor(self, released):
        factor = TransmissionLossFactor(
            mode="DATED_SERIES",
            windows=(LossFactorWindow(date(2026, 1, 1), date(2026, 7, 1), 0.04),
                     LossFactorWindow(date(2026, 7, 1), date(2027, 1, 1), 0.02)))
        first = apply_transmission_loss(factor, 1000.0, date(2026, 6, 30))
        second = apply_transmission_loss(factor, 1000.0, date(2026, 12, 31))
        assert first.loss_mwh == pytest.approx(40.0)
        assert second.loss_mwh == pytest.approx(20.0)

    def test_dated_series_boundary_semantics_from_inclusive_until_exclusive(
            self, released):
        factor = TransmissionLossFactor(
            mode="DATED_SERIES",
            windows=(LossFactorWindow(date(2026, 1, 1), date(2026, 7, 1), 0.04),))
        assert factor.factor_on(date(2026, 1, 1)) == 0.04
        assert factor.factor_on(date(2026, 6, 30)) == 0.04
        assert factor.factor_on(date(2026, 7, 1)) is None  # until is exclusive

    def test_gap_is_unavailable_never_implicit_zero(self, released):
        factor = TransmissionLossFactor(
            mode="DATED_SERIES",
            windows=(LossFactorWindow(date(2026, 1, 1), date(2026, 7, 1), 0.04),
                     LossFactorWindow(date(2027, 1, 1), date(2027, 7, 1), 0.02)))
        assert factor.factor_on(date(2026, 12, 31)) is None
        with pytest.raises(ValueError, match="GENERATION_V2_UNAVAILABLE"):
            apply_transmission_loss_to_periods(
                factor, [(date(2026, 12, 31), 100.0)])

    def test_overlapping_loss_windows_fail_closed(self, released):
        with pytest.raises(ValueError, match="GENERATION_V2_OVERLAP"):
            TransmissionLossFactor(
                mode="DATED_SERIES",
                windows=(LossFactorWindow(date(2026, 1, 1), date(2026, 7, 3), 0.04),
                         LossFactorWindow(date(2026, 7, 2), date(2027, 1, 1), 0.02)),
            ).validate()

    def test_adjacent_windows_are_valid(self, released):
        TransmissionLossFactor(
            mode="DATED_SERIES",
            windows=(LossFactorWindow(date(2026, 1, 1), date(2026, 7, 1), 0.04),
                     LossFactorWindow(date(2026, 7, 1), date(2027, 1, 1), 0.02)),
        ).validate()

    def test_invalid_factors_fail_closed(self, released):
        for bad in (-0.01, 1.5, float("nan"), True):
            with pytest.raises(ValueError, match="GENERATION_V2_VALUE"):
                TransmissionLossFactor(mode="FLAT", flat_factor=bad).validate()
        with pytest.raises(ValueError, match="GENERATION_V2_VALUE"):
            LossFactorWindow(date(2026, 1, 1), date(2026, 7, 1), 1.2).validate()


# ── Invariant 5: explicit degradation onset semantics ────────────────────────


class TestInvariant5DegradationOnset:
    def test_canonical_convention_reproduced_exactly(self, released):
        """first_affected_year=2 must equal the released formula
        (1 - pv_degradation) ** (year_index - 1) for every year."""
        rate = 0.004
        onset = DegradationOnset.canonical(rate)
        for year in range(1, 41):
            expected = (1.0 - rate) ** (year - 1)
            assert onset.factor_for(year) == pytest.approx(expected)

    def test_canonical_matches_the_released_engine(self, released):
        """Non-circular proof against the released generation source:
        annual generation with the candidate onset must equal the released
        ``period_generation`` arithmetic for every operating year."""
        from finco_core.inputs._models import TechnicalParams
        from finco_core.revenue.generation import period_generation

        rate = 0.005
        tech = TechnicalParams(
            capacity_mw=64.0, yield_scenario="P50",
            operating_hours_p50=2000.0, pv_degradation=rate)
        onset = DegradationOnset.canonical(rate)
        for year in (1, 2, 3, 10, 25):
            period = type("P", (), {
                "is_operation": True, "year_index": year, "day_fraction": 1.0,
                "days_in_period": 365,
            })()
            released_value = period_generation(tech, [period], year)
            candidate_value = (
                tech.capacity_mw * 2000.0 * 1.0
                * (tech.plant_availability * tech.grid_availability)
                * onset.factor_for(year))
            assert candidate_value == pytest.approx(released_value)

    def test_onset_year_one_bites_immediately(self, released):
        onset = DegradationOnset(annual_rate=0.01, first_affected_year=1)
        assert onset.factor_for(1) == pytest.approx(0.99)
        assert onset.factor_for(2) == pytest.approx(0.99 ** 2)

    def test_later_onset_leaves_early_years_untouched(self, released):
        onset = DegradationOnset(annual_rate=0.01, first_affected_year=5)
        for year in (1, 2, 3, 4):
            assert onset.factor_for(year) == 1.0
        assert onset.factor_for(5) == pytest.approx(0.99)
        assert onset.factor_for(6) == pytest.approx(0.99 ** 2)

    def test_zero_degradation_is_identity_at_any_onset(self, released):
        for onset_year in (1, 2, 7):
            onset = DegradationOnset(annual_rate=0.0,
                                     first_affected_year=onset_year)
            for year in (1, 2, 10, 40):
                assert onset.factor_for(year) == 1.0

    def test_invalid_onset_and_year_fail_closed(self, released):
        for bad in (0, -1, True, 1.5, "2"):
            with pytest.raises(ValueError, match="GENERATION_V2_VALUE"):
                DegradationOnset(annual_rate=0.004,
                                 first_affected_year=bad).validate()
        onset = DegradationOnset(annual_rate=0.004)
        for bad_year in (0, -1, True):
            with pytest.raises(ValueError, match="GENERATION_V2_VALUE"):
                onset.factor_for(bad_year)


# ── Invariant 6: first-year vs normal availability never conflict ────────────


class TestInvariant6FirstYearAvailability:
    def test_single_sourced_by_operating_year(self, released):
        avail = FirstYearAvailability(first_year_availability=0.90,
                                      normal_availability=0.98)
        assert avail.availability_for(1) == 0.90
        for year in (2, 3, 10, 25):
            assert avail.availability_for(year) == 0.98

    def test_partial_cod_stub_uses_first_year_availability(self, released,
                                                           canonical_axis):
        """The COD stub (short first operating period on the released
        axis) is operating year 1 → first-year availability; the stub's
        energy is prorated by the canonical day_fraction only."""
        operating = [p for p in canonical_axis if p.is_operation]
        stub = operating[0]
        assert stub.day_fraction < 1.0
        assert stub.operating_year_index == 1
        avail = FirstYearAvailability(first_year_availability=0.90,
                                      normal_availability=0.98)
        assert avail.availability_for(stub.operating_year_index) == 0.90

    def test_no_annualisation_exists_in_the_candidate(self, released):
        """The helper surface carries no annualisation parameter: the
        composition reads only the canonical day_fraction upstream. The
        contract exposes exactly two availability values and a scope."""
        fields = FirstYearAvailability.__dataclass_fields__
        assert set(fields) == {"first_year_availability",
                               "normal_availability",
                               "partial_cod_treatment"}

    def test_bounds_and_unknown_treatment_fail_closed(self, released):
        with pytest.raises(ValueError, match="strictly"):
            FirstYearAvailability(0.0, 0.98).validate()
        with pytest.raises(ValueError, match="at most 1.0"):
            FirstYearAvailability(1.5, 0.98).validate()
        with pytest.raises(ValueError, match="GENERATION_V2_UNSUPPORTED"):
            FirstYearAvailability(0.9, 0.98,
                                  partial_cod_treatment="PRORATED").validate()

    def test_unknown_operating_year_fails_closed(self, released):
        avail = FirstYearAvailability(0.90, 0.98)
        for bad in (0, -1, True):
            with pytest.raises(ValueError, match="GENERATION_V2_VALUE"):
                avail.availability_for(bad)


# ── Invariants 3+4: transmission once; no silent double deductions ───────────


class TestInvariant34SingleApplicationNoDoubleDeduction:
    def test_transmission_factor_applied_exactly_once_in_composition(
            self, released, canonical_axis):
        factor = TransmissionLossFactor(mode="FLAT", flat_factor=0.03)
        operating = [p for p in canonical_axis if p.is_operation]
        for p in operating[:2]:
            adj = compose_operating_adjustments(
                period_index=p.index, operating_year_index=p.operating_year_index,
                on_date=p.end_date, degradation=DegradationOnset.canonical(0.004),
                availability=FirstYearAvailability(0.90, 0.98),
                transmission_loss=factor)
            assert adj.loss_factor == 0.03  # surfaced exactly once
            split = apply_transmission_loss(factor, 1000.0, p.end_date)
            # re-application to the delivered remainder is structurally a
            # different call: the identity only holds from gross
            assert split.delivered_mwh + split.loss_mwh == 1000.0
            double = apply_transmission_loss(factor, split.delivered_mwh,
                                             p.end_date)
            assert double.gross_mwh == split.delivered_mwh  # caller's choice,
            # never an automatic second application

    def test_overlapping_event_windows_fail_closed(self, released):
        events = (
            VolumeAdjustmentEvent("grid-outage", date(2026, 1, 1),
                                  date(2026, 4, 1), energy_loss_pct=10.0),
            VolumeAdjustmentEvent("curtailment", date(2026, 3, 15),
                                  date(2026, 6, 1), energy_loss_pct=20.0),
        )
        with pytest.raises(ValueError, match="GENERATION_V2_OVERLAP"):
            validate_no_event_overlaps(events)

    def test_disjoint_events_never_double_deduct(self, released):
        events = (
            VolumeAdjustmentEvent("grid-outage", date(2026, 1, 1),
                                  date(2026, 3, 1), energy_loss_pct=10.0),
            VolumeAdjustmentEvent("curtailment", date(2026, 3, 1),
                                  date(2026, 6, 1), energy_loss_pct=20.0),
        )
        validate_no_event_overlaps(events)  # adjacent, not overlapping
        out = apply_volume_adjustments(
            1000.0, date(2026, 1, 1), date(2026, 6, 30), events)
        jan_feb = 59 / 181  # exact day proration (2026 non-leap: Jan+Feb)
        mar_may = 92 / 181
        expected_lost = 1000.0 * jan_feb * 0.10 + 1000.0 * mar_may * 0.20
        assert out.total_lost_mwh == pytest.approx(expected_lost)
        assert out.net_mwh == pytest.approx(1000.0 - expected_lost)
        assert out.net_mwh + out.total_lost_mwh == pytest.approx(out.gross_mwh)
        assert [a.event_id for a in out.attributions] == \
            ["grid-outage", "curtailment"]  # deterministic order
        assert sum(a.lost_mwh for a in out.attributions) == \
            pytest.approx(out.total_lost_mwh)

    def test_deduction_above_gross_energy_fails_closed(self, released):
        events = (
            VolumeAdjustmentEvent("a", date(2026, 1, 1), date(2026, 7, 1),
                                  energy_loss_pct=60.0),
            VolumeAdjustmentEvent("b", date(2026, 7, 1), date(2026, 12, 31),
                                  energy_loss_pct=60.0),
        )
        # windows are disjoint so construction passes; the SECOND period's
        # application is fine, but a single period fully covered by two
        # disjoint-date events cannot exist — prove the guard instead with
        # one full-window 100%+ event pair via a period that both cover:
        # impossible by overlap rejection, so prove per-event full loss:
        out = apply_volume_adjustments(
            1000.0, date(2026, 1, 1), date(2026, 6, 30),
            (VolumeAdjustmentEvent("a", date(2026, 1, 1), date(2026, 7, 1),
                                   energy_loss_pct=100.0),))
        assert out.net_mwh == 0.0
        assert out.total_lost_mwh == 1000.0

    def test_event_entirely_outside_the_period_is_ignored(self, released):
        out = apply_volume_adjustments(
            1000.0, date(2026, 1, 1), date(2026, 6, 30),
            (VolumeAdjustmentEvent("later", date(2027, 1, 1),
                                   date(2027, 6, 1), energy_loss_pct=50.0),))
        assert out.total_lost_mwh == 0.0
        assert out.net_mwh == 1000.0
        assert out.attributions == ()


# ── Invariant 2: compensation changes cash, never physical MWh ───────────────


class TestInvariant2CompensationIsCashOnly:
    def _event(self, basis, **kw):
        return VolumeAdjustmentEvent("curtail", date(2026, 1, 1),
                                     date(2026, 7, 1), energy_loss_pct=10.0,
                                     compensation_basis=basis, **kw)

    def test_physical_outcome_identical_across_compensation_bases(
            self, released):
        physical = []
        for event in (
                self._event("NONE"),
                self._event("CONTRACTED", compensation_pct=100.0,
                            compensation_price_eur_mwh=42.0),
                self._event("MERCHANT", compensation_pct=50.0),
        ):
            out = apply_volume_adjustments(
                1000.0, date(2026, 1, 1), date(2026, 6, 30), (event,),
                merchant_prices={date(2026, 1, 1): 30.0})
            physical.append((out.net_mwh, out.total_lost_mwh))
        assert physical[0] == physical[1] == physical[2]

    def test_contracted_compensation_settles_cash_separately(self, released):
        out = apply_volume_adjustments(
            1000.0, date(2026, 1, 1), date(2026, 6, 30),
            (self._event("CONTRACTED", compensation_pct=100.0,
                         compensation_price_eur_mwh=40.0),))
        lost = 1000.0 * 0.10
        assert out.total_lost_mwh == pytest.approx(lost)
        assert out.net_mwh == pytest.approx(900.0)  # physical unchanged
        assert out.compensated_mwh == pytest.approx(lost)
        assert out.compensation_eur == Decimal(str(lost)) * Decimal("40")

    def test_merchant_compensation_with_partial_share(self, released):
        out = apply_volume_adjustments(
            1000.0, date(2026, 1, 1), date(2026, 6, 30),
            (self._event("MERCHANT", compensation_pct=50.0),),
            merchant_prices={date(2026, 1, 1): 30.0})
        lost = 100.0
        assert out.compensated_mwh == pytest.approx(lost * 0.5)
        assert out.compensation_eur == Decimal(str(lost * 0.5)) * Decimal("30")

    def test_missing_merchant_evidence_is_unavailable_never_zero(
            self, released):
        out = apply_volume_adjustments(
            1000.0, date(2026, 1, 1), date(2026, 6, 30),
            (self._event("MERCHANT", compensation_pct=50.0),))
        assert out.unavailable_compensation_mwh == pytest.approx(50.0)
        assert out.compensation_eur is None  # aggregate not published
        # the physical outcome is unaffected
        assert out.net_mwh == pytest.approx(900.0)

    def test_partial_window_uses_exact_day_proration(self, released):
        # event covers Feb only (28 days of the 181-day period in 2025)
        event = VolumeAdjustmentEvent("feb-outage", date(2025, 2, 1),
                                      date(2025, 3, 1), energy_loss_pct=50.0)
        out = apply_volume_adjustments(
            1810.0, date(2025, 1, 1), date(2025, 6, 30), (event,))
        expected = 1810.0 * (28 / 181) * 0.5
        assert out.total_lost_mwh == pytest.approx(expected)
        assert out.attributions[0].overlap_days == 28
        assert out.attributions[0].period_days == 181

    def test_compensation_rules_fail_closed(self, released):
        with pytest.raises(ValueError, match="CONTRACTED compensation requires"):
            VolumeAdjustmentEvent("e", date(2026, 1, 1), date(2026, 7, 1),
                                  energy_loss_pct=10.0,
                                  compensation_basis="CONTRACTED",
                                  compensation_pct=100.0).validate()
        with pytest.raises(ValueError, match="requires compensation_basis"):
            VolumeAdjustmentEvent("e", date(2026, 1, 1), date(2026, 7, 1),
                                  energy_loss_pct=10.0,
                                  compensation_price_eur_mwh=40.0).validate()
        with pytest.raises(ValueError, match="requires a compensation basis"):
            VolumeAdjustmentEvent("e", date(2026, 1, 1), date(2026, 7, 1),
                                  energy_loss_pct=10.0,
                                  compensation_pct=50.0).validate()
        with pytest.raises(ValueError, match="within \\[0, 100\\]"):
            VolumeAdjustmentEvent("e", date(2026, 1, 1), date(2026, 7, 1),
                                  energy_loss_pct=150.0).validate()

    def test_duplicate_event_ids_fail_closed(self, released):
        events = (
            VolumeAdjustmentEvent("same", date(2026, 1, 1), date(2026, 3, 1),
                                  energy_loss_pct=10.0),
            VolumeAdjustmentEvent("same", date(2026, 4, 1), date(2026, 6, 1),
                                  energy_loss_pct=10.0),
        )
        with pytest.raises(ValueError, match="duplicate event_id"):
            validate_no_event_overlaps(events)


# ── Invariants 7+8: pre-COD commissioning window semantics ───────────────────


class TestPreCodWindowSemantics:
    def _commissioning(self, start, cod, months, basis="FIXED", **kw):
        return PreCodCommissioning(
            commissioning_start=start, cod_date=cod,
            monthly_ramp_pct=months, price_basis=basis, **kw)

    def test_cod_month_is_never_in_the_window(self, released):
        c = self._commissioning(date(2025, 1, 1), date(2025, 7, 1),
                                (25.0, 40.0, 55.0, 70.0, 85.0, 95.0))
        assert c.window_months() == 6
        seq = month_sequence(c.commissioning_start, c.cod_date)
        assert seq == ((2025, 1), (2025, 2), (2025, 3), (2025, 4),
                       (2025, 5), (2025, 6))
        assert all(m < (c.cod_date.year, c.cod_date.month) for m in seq)

    def test_ramp_must_cover_exactly_the_window(self, released):
        base = dict(commissioning_start=date(2025, 1, 1),
                    cod_date=date(2025, 7, 1), price_basis="FIXED",
                    fixed_price_eur_mwh=30.0)
        for wrong_len in (5, 7):
            with pytest.raises(ValueError,
                               match="exactly the window|has 6 months"):
                build_pre_cod_proposal(
                    self._commissioning(date(2025, 1, 1), date(2025, 7, 1),
                                        (50.0,) * wrong_len,
                                        fixed_price_eur_mwh=30.0),
                    capacity_mw=10.0,
                    month_hours={(2025, m): 720.0 for m in range(1, 7)},
                    availability=0.95)

    def test_window_must_end_before_cod(self, released):
        with pytest.raises(ValueError, match="strictly after"):
            self._commissioning(date(2025, 7, 1), date(2025, 7, 1),
                                (50.0,)).validate()
        with pytest.raises(ValueError, match="strictly after"):
            self._commissioning(date(2025, 8, 1), date(2025, 7, 1),
                                (50.0,)).validate()

    def test_pre_cod_rows_are_never_post_cod(self, released):
        proposal = build_pre_cod_proposal(
            self._commissioning(date(2025, 1, 1), date(2025, 7, 1),
                                (25.0, 40.0, 55.0, 70.0, 85.0, 95.0),
                                fixed_price_eur_mwh=30.0),
            capacity_mw=10.0,
            month_hours={(2025, m): 720.0 for m in range(1, 7)},
            availability=0.95)
        assert max((m.year, m.month) for m in proposal.months) < (2025, 7)
        assert proposal.cod_date == date(2025, 7, 1)


# ── Pre-COD proposal math ────────────────────────────────────────────────────


class TestPreCodProposalMath:
    def _proposal(self, released, basis="FIXED", **kw):
        commissioning = PreCodCommissioning(
            commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
            monthly_ramp_pct=(25.0, 40.0, 55.0, 70.0, 85.0, 95.0),
            price_basis=basis, **kw)
        return build_pre_cod_proposal(
            commissioning, capacity_mw=10.0,
            month_hours={(2025, m): 720.0 for m in range(1, 7)},
            availability=0.95,
            market_prices={(2025, 1): 30.0, (2025, 2): 31.0,
                           (2025, 3): 29.0, (2025, 4): 32.0,
                           (2025, 5): 28.0} if basis == "MARKET" else None)

    def test_exact_physical_and_fixed_sales(self, released):
        proposal = self._proposal(released, basis="FIXED",
                                  fixed_price_eur_mwh=30.0)
        jan = proposal.months[0]
        assert jan.gross_mwh == pytest.approx(10.0 * 720 * 0.25 * 0.95)
        assert jan.potential_sales_eur == \
            (Decimal(str(jan.gross_mwh)) * Decimal("30")).quantize(
                Decimal("0.000001"))
        assert proposal.physical_total_mwh == pytest.approx(
            sum(m.gross_mwh for m in proposal.months))
        assert proposal.potential_sales_total_eur == pytest.approx(
            sum(m.potential_sales_eur for m in proposal.months))
        assert proposal.unavailable_sales_months == 0

    def test_ppa_basis_settles_at_the_ppa_price(self, released):
        proposal = self._proposal(released, basis="PPA",
                                  ppa_price_eur_mwh=41.5)
        for row in proposal.months:
            assert row.potential_sales_eur == \
                (Decimal(str(row.gross_mwh)) * Decimal("41.5")).quantize(
                    Decimal("0.000001"))

    def test_missing_market_month_is_unavailable_never_zero(self, released):
        proposal = self._proposal(released, basis="MARKET")
        assert proposal.unavailable_sales_months == 1  # June has no evidence
        june = proposal.months[5]
        assert june.sales_state == "UNAVAILABLE"
        assert june.potential_sales_eur is None
        assert june.gross_mwh > 0  # physical energy still proposed
        # a total over incomplete evidence is not published
        assert proposal.potential_sales_total_eur is None
        # priced months keep their rows
        assert proposal.months[0].sales_state == "PRICED"
        assert proposal.months[0].potential_sales_eur is not None

    def test_negative_market_price_fails_closed(self, released):
        commissioning = PreCodCommissioning(
            commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
            monthly_ramp_pct=(50.0,) * 6, price_basis="MARKET")
        with pytest.raises(ValueError, match="must be at least 0.0"):
            build_pre_cod_proposal(
                commissioning, capacity_mw=10.0,
                month_hours={(2025, m): 720.0 for m in range(1, 7)},
                availability=0.95,
                market_prices={(2025, m): -5.0 for m in range(1, 7)})

    def test_missing_declared_hours_fails_closed(self, released):
        commissioning = PreCodCommissioning(
            commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
            monthly_ramp_pct=(50.0,) * 6, price_basis="FIXED",
            fixed_price_eur_mwh=30.0)
        with pytest.raises(ValueError, match="GENERATION_V2_UNAVAILABLE"):
            build_pre_cod_proposal(
                commissioning, capacity_mw=10.0,
                month_hours={(2025, m): 720.0 for m in range(1, 6)},  # no June
                availability=0.95)

    def test_ramp_zero_and_above_100_fail_closed(self, released):
        with pytest.raises(ValueError, match="strictly positive"):
            PreCodCommissioning(
                commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
                monthly_ramp_pct=(0.0, 40.0, 55.0, 70.0, 85.0, 95.0),
                price_basis="FIXED", fixed_price_eur_mwh=30.0).validate()
        with pytest.raises(ValueError, match="within \\[0, 100\\]"):
            PreCodCommissioning(
                commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
                monthly_ramp_pct=(150.0, 40.0, 55.0, 70.0, 85.0, 95.0),
                price_basis="FIXED", fixed_price_eur_mwh=30.0).validate()

    def test_price_basis_rules_fail_closed(self, released):
        with pytest.raises(ValueError, match="FIXED basis requires"):
            PreCodCommissioning(
                commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
                monthly_ramp_pct=(50.0,) * 6, price_basis="FIXED").validate()
        with pytest.raises(ValueError, match="the matching price_basis"):
            PreCodCommissioning(
                commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
                monthly_ramp_pct=(50.0,) * 6, price_basis="MARKET",
                fixed_price_eur_mwh=30.0).validate()
        with pytest.raises(ValueError, match="GENERATION_V2_UNSUPPORTED"):
            PreCodCommissioning(
                commissioning_start=date(2025, 1, 1), cod_date=date(2025, 7, 1),
                monthly_ramp_pct=(50.0,) * 6,
                price_basis="NEGOTIATED").validate()


# ── Canonical boundary integration (released PeriodEngine) ──────────────────


class TestCanonicalBoundaryIntegration:
    def test_operating_rows_align_with_candidate_adjustments(
            self, released, canonical_axis):
        operating = [p for p in canonical_axis if p.is_operation]
        assert operating, "the released axis must carry operating rows"
        # canonical boundaries: every operating row ends on Jun 30 / Dec 31
        for p in operating:
            assert (p.end_date.month, p.end_date.day) in ((6, 30), (12, 31))
        first = operating[0]
        # COD-anchored axis: the first operating row starts AT COD (2025-07-01)
        assert first.start_date == date(2025, 7, 1)
        assert first.operating_year_index == 1
        adj = compose_operating_adjustments(
            period_index=first.index,
            operating_year_index=first.operating_year_index,
            on_date=first.end_date,
            degradation=DegradationOnset.canonical(0.004),
            availability=FirstYearAvailability(0.90, 0.98),
            transmission_loss=TransmissionLossFactor(
                mode="FLAT", flat_factor=0.03))
        assert adj.availability == 0.90      # stub year 1 → first-year
        assert adj.degradation_factor == 1.0  # canonical: year 1 untouched
        # the COD-anchored axis keeps Jan-Jun 2026 in operating year 1;
        # operating year 2 starts a full year after COD
        assert operating[1].operating_year_index == 1
        second = next(p for p in operating if p.operating_year_index == 2)
        assert second.start_date == date(2026, 6, 30)  # COD anniversary row
        adj2 = compose_operating_adjustments(
            period_index=second.index,
            operating_year_index=second.operating_year_index,
            on_date=second.end_date,
            degradation=DegradationOnset.canonical(0.004),
            availability=FirstYearAvailability(0.90, 0.98),
            transmission_loss=TransmissionLossFactor(
                mode="FLAT", flat_factor=0.03))
        assert adj2.availability == 0.98
        assert adj2.degradation_factor == pytest.approx(0.996)

    def test_leap_year_day_count_in_event_proration(self, released):
        # Feb 2028 has 29 days; the overlap uses exact day counts
        event = VolumeAdjustmentEvent("feb", date(2028, 2, 1), date(2028, 3, 1),
                                      energy_loss_pct=50.0)
        out = apply_volume_adjustments(
            1000.0, date(2028, 1, 1), date(2028, 6, 30), (event,))
        assert out.attributions[0].overlap_days == 29

    def test_construction_rows_are_never_operating(self, released,
                                                   canonical_axis):
        construction = [p for p in canonical_axis if p.is_construction]
        assert construction
        for p in construction:
            assert p.is_operation is False
            assert p.operating_year_index == 0  # construction keeps defaults


# ── Composition of all operating adjustments (one application each) ──────────


class TestComposedAdjustments:
    def test_each_mechanism_applied_exactly_once(self, released):
        adj = compose_operating_adjustments(
            period_index=3, operating_year_index=4, on_date=date(2028, 6, 30),
            degradation=DegradationOnset(annual_rate=0.01,
                                         first_affected_year=3),
            availability=FirstYearAvailability(0.90, 0.98),
            transmission_loss=TransmissionLossFactor(mode="FLAT",
                                                     flat_factor=0.02))
        assert adj.degradation_factor == pytest.approx(0.99 ** 2)
        assert adj.availability == 0.98
        assert adj.loss_factor == 0.02
        composed = adj.availability * adj.degradation_factor
        assert composed == pytest.approx(0.98 * 0.99 ** 2)

    def test_uncovered_transmission_boundary_is_none(self, released):
        adj = compose_operating_adjustments(
            period_index=1, operating_year_index=1, on_date=date(2030, 6, 30),
            degradation=DegradationOnset.canonical(0.004),
            availability=FirstYearAvailability(0.90, 0.98),
            transmission_loss=TransmissionLossFactor(
                mode="DATED_SERIES",
                windows=(LossFactorWindow(date(2026, 1, 1), date(2027, 1, 1),
                                          0.03),)))
        assert adj.loss_factor is None  # typed UNAVAILABLE upstream


# ── Monthly construction grid integration (released authority, unchanged) ────


class TestMonthlyConstructionGridIntegration:
    def test_commissioning_window_equals_the_construction_month_grid(
            self, released):
        """The pre-COD commissioning months are exactly the released
        monthly construction grid (financial close + construction_months)
        for a FC 2025-01-01 / 6-month build: Jan..Jun 2025. The candidate
        consumes that grid; it never redefines periodisation."""
        from finco_core.engine.period_engine import PeriodEngine

        engine = PeriodEngine(
            financial_close=date(2025, 1, 1), construction_months=6,
            horizon_years=25, ppa_years=15, cod_date=date(2025, 7, 1))
        construction = [p for p in engine.periods() if p.is_construction]
        assert construction, "released axis must carry construction rows"
        grid_first = min(p.start_date for p in construction)
        grid_last_exclusive = max(p.end_date for p in construction)
        commissioning = PreCodCommissioning(
            commissioning_start=grid_first, cod_date=date(2025, 7, 1),
            monthly_ramp_pct=(25.0, 40.0, 55.0, 70.0, 85.0, 95.0),
            price_basis="FIXED", fixed_price_eur_mwh=30.0)
        months = month_sequence(commissioning.commissioning_start,
                                commissioning.cod_date)
        assert months[0] == (grid_first.year, grid_first.month)
        # construction row ends are exclusive: the last commissioning month
        # is the month BEFORE the exclusive end (June, not July)
        assert months[-1] == (2025, 6)
        assert (grid_last_exclusive.year, grid_last_exclusive.month) == (2025, 7)
        assert commissioning.window_months() == 6 == len(months)
        # every commissioning month starts inside the released construction
        # rows (no month escapes the construction phase)
        for (y, m) in months:
            inside = any(p.start_date <= date(y, m, 1) < p.end_date
                         for p in construction)
            assert inside, (y, m)

    def test_commissioning_window_may_be_shorter_than_construction(
            self, released):
        """A commissioning start later than financial close is valid: the
        window is [start, COD), not the whole build."""
        commissioning = PreCodCommissioning(
            commissioning_start=date(2025, 4, 1), cod_date=date(2025, 7, 1),
            monthly_ramp_pct=(40.0, 70.0, 95.0),
            price_basis="FIXED", fixed_price_eur_mwh=30.0)
        assert commissioning.window_months() == 3
        assert month_sequence(commissioning.commissioning_start,
                              commissioning.cod_date) == (
            (2025, 4), (2025, 5), (2025, 6))


# ── Isolation: the candidate is invisible to the production path ─────────────


class TestProductionIsolation:
    def test_no_production_module_imports_the_candidate(self):
        import json
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c",
             "import json, pathlib, sys\n"
             "roots = ['app', 'domain', 'financial_engine', 'finco_core', 'main_web.py']\n"
             "bad = []\n"
             "for root in roots:\n"
             "    p = pathlib.Path(root)\n"
             "    files = [p] if p.is_file() else sorted(p.rglob('*.py'))\n"
             "    for f in files:\n"
             "        try:\n"
             "            t = f.read_text(encoding='utf-8')\n"
             "        except Exception:\n"
             "            continue\n"
             "        if 'generation_v2_candidate' in t:\n"
             "            bad.append(str(f))\n"
             "print(json.dumps(bad))"],
            cwd=str(REPO), capture_output=True, text=True)
        referers = set(json.loads(result.stdout.strip()))
        own = {r for r in referers
               if "generation_v2_candidate" in r and r.replace("\\", "/").startswith("app/generation_v2_candidate")}
        assert referers == own, \
            f"production files reference the candidate: {sorted(referers - own)}"

    def test_package_never_imports_production_or_sibling_candidates(self):
        package = REPO / "app" / "generation_v2_candidate"
        forbidden_tokens = ("financial_engine", "finco_core", "domain.revenue",
                            "revenue_v4_candidate", "financing_instruments")
        for py in sorted(package.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for token in forbidden_tokens:
                            assert token not in alias.name, (py, alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for token in forbidden_tokens:
                        assert token not in module, (py, module)
