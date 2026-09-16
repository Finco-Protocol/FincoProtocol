"""Read-only verification of serialized FINCO Model production output."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


MODEL_VALIDATION_SCHEMA = "finco.model-validation.v1"
DEFAULT_ABS_TOL_KEUR = Decimal("0.10")
DEFAULT_REL_TOL = Decimal("1e-9")


@dataclass(frozen=True)
class InvariantCheck:
    invariant_id: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "invariantId": self.invariant_id,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ModelValidationReport:
    schema: str
    project_type: str
    scenario: str
    checks: tuple[InvariantCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[InvariantCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "projectType": self.project_type,
            "scenario": self.scenario,
            "passed": self.passed,
            "checks": [check.as_dict() for check in self.checks],
        }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _close(
    left: Any,
    right: Any,
    *,
    abs_tol: Decimal,
    rel_tol: Decimal,
) -> bool:
    a = _decimal(left)
    b = _decimal(right)
    if a is None or b is None:
        return False
    difference = abs(a - b)
    scale = max(abs(a), abs(b))
    return difference <= max(abs_tol, rel_tol * scale)


def _check(invariant_id: str, passed: bool, detail: str) -> InvariantCheck:
    return InvariantCheck(invariant_id=invariant_id, passed=bool(passed), detail=detail)


def validate_model_run(
    payload: Mapping[str, Any],
    *,
    abs_tol_keur: Decimal = DEFAULT_ABS_TOL_KEUR,
    rel_tol: Decimal = DEFAULT_REL_TOL,
) -> ModelValidationReport:
    """Reconcile already-computed Model output surfaces.

    The verifier is not a second financial engine. It checks identities and
    cross-view consistency in the serialized production result returned by
    ``app.api.project_runner.run_project``. Missing or malformed evidence on an
    applicable operation period fails closed; construction/pre-operation rows
    and operation rows where the serializer declares no senior-debt evidence and
    no active senior balance remain legitimate N/A states.
    """

    checks: list[InvariantCheck] = []
    project_type = str(payload.get("project_type") or "")
    scenario = str(payload.get("scenario") or "")
    kpis = _mapping(payload.get("kpis"))

    messages = _sequence(payload.get("messages"))
    checks.append(_check("MODEL_RUN_MESSAGES_EMPTY", len(messages) == 0, f"messages={len(messages)}"))

    authority = _mapping(payload.get("runtime_authority"))
    authority_ok = (
        authority.get("classification") == "CLEAN_PRODUCTION_READY"
        and authority.get("runtime_authority") == "clean_g2c"
        and authority.get("calculation_count") == 1
        and bool(authority.get("clean_entry_point"))
    )
    checks.append(
        _check(
            "MODEL_SINGLE_RUNTIME_AUTHORITY",
            authority_ok,
            (
                "clean G2C authority with calculation_count=1"
                if authority_ok
                else f"authority={dict(authority)!r}"
            ),
        )
    )

    required_kpis = (
        "total_capex_keur",
        "total_revenue_keur",
        "total_ebitda_keur",
        "total_opex_keur",
        "project_irr",
        "min_dscr",
    )
    nonfinite = [name for name in required_kpis if _decimal(kpis.get(name)) is None]
    checks.append(
        _check(
            "MODEL_REQUIRED_KPIS_FINITE",
            not nonfinite,
            "all required KPIs finite" if not nonfinite else f"non-finite={nonfinite!r}",
        )
    )

    revenue = _decimal(kpis.get("total_revenue_keur"))
    opex = _decimal(kpis.get("total_opex_keur"))
    ebitda = _decimal(kpis.get("total_ebitda_keur"))
    ebitda_identity = False
    if revenue is not None and opex is not None and ebitda is not None:
        ebitda_identity = _close(
            revenue - opex,
            ebitda,
            abs_tol=abs_tol_keur,
            rel_tol=rel_tol,
        )
    checks.append(
        _check(
            "MODEL_EBITDA_IDENTITY",
            ebitda_identity,
            "total EBITDA = total revenue - total OPEX",
        )
    )

    min_dscr = _decimal(kpis.get("min_dscr"))
    checks.append(
        _check(
            "MODEL_MIN_DSCR_POSITIVE",
            min_dscr is not None and min_dscr > 0,
            f"min_dscr={kpis.get('min_dscr')!r}",
        )
    )

    debt = _mapping(payload.get("debt_schedule"))
    debt_periods = _sequence(debt.get("periods"))
    debt_failures: list[int] = []
    operation_dates: set[str] = set()
    applicable_debt_periods = 0
    debt_fields = (
        "senior_principal_keur",
        "senior_interest_keur",
        "senior_ds_keur",
    )
    for index, raw_period in enumerate(debt_periods):
        period = _mapping(raw_period)
        if period.get("is_operation") is not True:
            continue
        date_value = period.get("date")
        if isinstance(date_value, str) and date_value:
            operation_dates.add(date_value)

        raw_values = tuple(period.get(field) for field in debt_fields)
        senior_balance = _decimal(period.get("senior_balance_keur"))
        carries_debt_service_evidence = any(value is not None for value in raw_values)
        has_active_senior_balance = senior_balance is not None and senior_balance > 0
        if not carries_debt_service_evidence and not has_active_senior_balance:
            continue

        applicable_debt_periods += 1
        principal = _decimal(raw_values[0])
        interest = _decimal(raw_values[1])
        debt_service = _decimal(raw_values[2])
        if principal is None or interest is None or debt_service is None:
            debt_failures.append(index)
            continue
        if not _close(
            principal + interest,
            debt_service,
            abs_tol=abs_tol_keur,
            rel_tol=rel_tol,
        ):
            debt_failures.append(index)
    debt_identity_ok = (
        bool(debt_periods)
        and applicable_debt_periods > 0
        and not debt_failures
    )
    checks.append(
        _check(
            "MODEL_DEBT_SERVICE_IDENTITY",
            debt_identity_ok,
            (
                "all applicable operation debt rows have finite senior principal, interest "
                "and debt service; debt service = principal + interest"
                if debt_identity_ok
                else (
                    f"periodFailures={debt_failures!r}; "
                    f"applicableDebtPeriodCount={applicable_debt_periods}; "
                    f"periodCount={len(debt_periods)}"
                )
            ),
        )
    )

    debt_summary = _mapping(debt.get("summary"))
    checks.append(
        _check(
            "MODEL_DEBT_SUMMARY_RECONCILES_KPI",
            _close(
                debt_summary.get("total_senior_ds_keur"),
                kpis.get("total_senior_ds_keur"),
                abs_tol=abs_tol_keur,
                rel_tol=rel_tol,
            ),
            "debt schedule total senior service = KPI total senior service",
        )
    )

    tax = _mapping(payload.get("tax_schedule"))
    tax_summary = _mapping(tax.get("summary"))
    checks.append(
        _check(
            "MODEL_TAX_SUMMARY_RECONCILES_KPI",
            _close(
                tax_summary.get("total_tax_keur"),
                kpis.get("total_tax_keur"),
                abs_tol=abs_tol_keur,
                rel_tol=rel_tol,
            ),
            "tax schedule total = KPI total tax",
        )
    )

    distribution = _mapping(payload.get("distribution_schedule"))
    distribution_summary = _mapping(distribution.get("summary"))
    checks.append(
        _check(
            "MODEL_DISTRIBUTION_SUMMARY_RECONCILES_KPI",
            _close(
                distribution_summary.get("total_distribution_keur"),
                kpis.get("total_distributions_keur"),
                abs_tol=abs_tol_keur,
                rel_tol=rel_tol,
            ),
            "distribution schedule total = KPI total distributions",
        )
    )

    derivation = _mapping(payload.get("derivation_evidence"))
    dscr = _mapping(derivation.get("dscr"))
    sample_cfads = _decimal(dscr.get("sample_cfads_keur"))
    sample_ds = _decimal(dscr.get("sample_senior_debt_service_keur"))
    sample_dscr = _decimal(dscr.get("sample_dscr"))
    dscr_identity = False
    if (
        sample_cfads is not None
        and sample_ds is not None
        and sample_ds > 0
        and sample_dscr is not None
    ):
        dscr_identity = _close(
            sample_cfads / sample_ds,
            sample_dscr,
            abs_tol=Decimal("1e-9"),
            rel_tol=Decimal("1e-9"),
        )
    checks.append(
        _check(
            "MODEL_DSCR_SAMPLE_IDENTITY",
            dscr_identity,
            "sample DSCR = sample CFADS / sample senior debt service",
        )
    )

    fs = _mapping(payload.get("financial_statements"))
    pnl_periods = _sequence(_mapping(fs.get("pnl")).get("periods"))
    bs_periods = _sequence(_mapping(fs.get("balance_sheet")).get("periods"))
    cash_periods = _sequence(_mapping(fs.get("pf_cash_waterfall")).get("periods"))
    checks.append(
        _check(
            "MODEL_FINANCIAL_STATEMENTS_PRESENT",
            bool(pnl_periods) and bool(bs_periods) and bool(cash_periods),
            f"pnl={len(pnl_periods)} bs={len(bs_periods)} cash={len(cash_periods)}",
        )
    )

    applicable_balance_rows: list[tuple[int, Mapping[str, Any]]] = [
        (index, _mapping(period))
        for index, period in enumerate(bs_periods)
        if _mapping(period).get("date") in operation_dates
    ]
    balance_checks = [
        (index, _decimal(period.get("balance_check_keur")))
        for index, period in applicable_balance_rows
    ]
    invalid_balance_periods = [
        index for index, value in balance_checks if value is None
    ]
    finite_balance_checks = [
        value for _, value in balance_checks if value is not None
    ]
    max_balance_check = max(
        (abs(value) for value in finite_balance_checks),
        default=None,
    )
    balance_ok = (
        bool(applicable_balance_rows)
        and not invalid_balance_periods
        and len(finite_balance_checks) == len(applicable_balance_rows)
        and max_balance_check is not None
        and max_balance_check <= abs_tol_keur
    )
    checks.append(
        _check(
            "MODEL_BALANCE_SHEET_BALANCES",
            balance_ok,
            (
                f"operation-period max_abs_balance_check_keur={str(max_balance_check)}; "
                f"operationPeriodCount={len(applicable_balance_rows)}"
                if balance_ok
                else (
                    f"invalidOperationPeriods={invalid_balance_periods!r}; "
                    f"max_abs_balance_check_keur={str(max_balance_check) if max_balance_check is not None else 'unavailable'}; "
                    f"operationPeriodCount={len(applicable_balance_rows)}"
                )
            ),
        )
    )

    return ModelValidationReport(
        schema=MODEL_VALIDATION_SCHEMA,
        project_type=project_type,
        scenario=scenario,
        checks=tuple(checks),
    )


def build_model_validation_claim(
    payload: Mapping[str, Any],
    report: ModelValidationReport | None = None,
) -> dict[str, Any]:
    """Build a stable public claim from a serialized production run."""

    resolved_report = report or validate_model_run(payload)
    kpis = _mapping(payload.get("kpis"))
    authority = _mapping(payload.get("runtime_authority"))
    selected_kpi_names = (
        "total_capex_keur",
        "total_revenue_keur",
        "total_ebitda_keur",
        "total_opex_keur",
        "project_irr",
        "equity_irr",
        "sponsor_irr",
        "total_senior_ds_keur",
        "total_tax_keur",
        "total_distributions_keur",
        "min_dscr",
        "avg_dscr",
        "min_llcr",
    )
    return {
        "schema": MODEL_VALIDATION_SCHEMA,
        "projectType": str(payload.get("project_type") or ""),
        "scenario": str(payload.get("scenario") or ""),
        "runtimeAuthority": {
            "classification": authority.get("classification"),
            "reasonCode": authority.get("reason_code"),
            "runtimeAuthority": authority.get("runtime_authority"),
            "cleanEntryPoint": authority.get("clean_entry_point"),
            "calculationCount": authority.get("calculation_count"),
        },
        "kpis": {name: kpis.get(name) for name in selected_kpi_names},
        "validation": resolved_report.as_dict(),
        "evidenceSources": {
            "debt": _mapping(payload.get("debt_schedule")).get("source"),
            "tax": _mapping(payload.get("tax_schedule")).get("source"),
            "distribution": _mapping(payload.get("distribution_schedule")).get("source"),
            "financialStatements": _mapping(payload.get("financial_statements")).get("source"),
        },
    }
