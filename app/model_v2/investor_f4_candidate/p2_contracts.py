"""F4/P2 proposed legal-equity terms (OFFLINE ONLY; never an authorized Run input).

Version 2 is distinct from P1's persisted version 1.  No default legal policy,
contract value, beneficiary, class priority, payment or valuation is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json


class P2ContractError(ValueError):
    """A fail-closed financial/legal-policy validation error with a stable code."""
    def __init__(self, code: str, explanation: str):
        self.code = code
        super().__init__(f"{code}: {explanation}")


def need(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise P2ContractError(code, message)


def dec(value, label: str, *, positive: bool = False) -> Decimal:
    # JSON float parsing uses Decimal; Python floats are refused rather than
    # silently laundering imprecise source amounts into the legal contract.
    need(type(value) in (str, int, Decimal), "P2_AMOUNT_TYPE", label)
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise P2ContractError("P2_AMOUNT_TYPE", label) from exc
    need(result.is_finite() and result >= 0 and (not positive or result > 0),
         "P2_AMOUNT_INVALID", label)
    return result


def identity(value, label: str) -> str:
    need(type(value) is str and bool(value.strip()) and value.strip() == value and
         len(value) <= 150, "P2_IDENTITY_INVALID", label)
    return value


def dte(value, label: str) -> date:
    need(type(value) is str and len(value) == 10, "P2_DATE_INVALID", label)
    try:
        d = date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise P2ContractError("P2_DATE_INVALID", label) from exc
    need(d.isoformat() == value, "P2_DATE_INVALID", label)
    return d


def shape(raw: object, allowed: tuple[str, ...], *, label: str) -> dict:
    need(type(raw) is dict and set(raw) == set(allowed),
         "P2_SCHEMA_INVALID", f"{label}: exact fields required {sorted(allowed)}")
    return raw


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "P2_DUPLICATE_KEY", key)
        result[key] = value
    return result


def canonical(document: object) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Investor:
    id: str
    class_id: str
    ownership: Decimal
    commitment: Decimal


@dataclass(frozen=True)
class EquityClass:
    id: str
    preferred_rate: Decimal | None


@dataclass(frozen=True)
class Contribution:
    investor_id: str
    when: date
    amount: Decimal


@dataclass(frozen=True)
class Stage:
    kind: str
    class_id: str | None
    beneficiary_id: str | None
    cap: Decimal | None
    fraction: Decimal | None


@dataclass(frozen=True)
class Contract:
    agreement_id: str
    version: int
    investors: tuple[Investor, ...]
    classes: tuple[EquityClass, ...]
    contributions: tuple[Contribution, ...]
    stages: tuple[Stage, ...]
    digest: str
    document: str


_CLASS_FIELDS = ("id", "preferred_rate_pa")
_INVESTOR_FIELDS = ("id", "class_id", "ownership_fraction", "commitment_keur")
_CONTRIBUTION_FIELDS = ("investor_id", "date", "amount_keur")
_STAGE_FIELDS = ("kind", "class_id", "beneficiary_id", "lifetime_cap_keur", "fraction")
_ROOT_FIELDS = ("schema_version", "approval", "agreement_id", "version", "currency", "unit",
                "preferred_method", "day_count", "accrual_start", "accrual_stop",
                "partial_return", "cash_shortfall", "hurdle_basis", "negative_distribution",
                "investors", "classes", "contributions", "stages")
_ALLOWED_KINDS = frozenset({"RETURN_OF_CAPITAL", "PREFERRED_RETURN", "CATCH_UP", "CARRY", "RESIDUAL"})


def parse_contract(raw: str) -> Contract:
    need(type(raw) is str and 0 < len(raw) <= 250_000, "P2_SCHEMA_INVALID", "JSON input")
    try:
        data = json.loads(raw, object_pairs_hook=unique, parse_float=Decimal,
                          parse_constant=lambda _: need(False, "P2_NONFINITE", "nonfinite JSON"))
    except (ValueError, TypeError) as exc:
        raise P2ContractError("P2_SCHEMA_INVALID", str(exc)) from exc
    shape(data, _ROOT_FIELDS, label="agreement")
    need(type(data["schema_version"]) is int and data["schema_version"] == 2 and
         type(data["version"]) is int and data["version"] > 0,
         "P2_VERSION_UNSUPPORTED", "only version 2 candidate; existing P1 remains version 1")
    expected = {
        "approval": "CANDIDATE_NOT_AUTHORIZED", "currency": "EUR", "unit": "kEUR",
        "preferred_method": "SIMPLE_ON_UNRETURNED_CAPITAL",
        "day_count": "ACT_365_FIXED", "accrual_start": "EACH_CONTRIBUTION_DATE",
        "accrual_stop": "EACH_RETURN_OF_CAPITAL_DATE",
        "partial_return": "REDUCE_FUTURE_ACCRUAL_BASE",
        "cash_shortfall": "CARRY_UNPAID_ENTITLEMENT",
        "hurdle_basis": "CUMULATIVE_UNPAID_PREF_NOT_IRR",
        "negative_distribution": "REJECT",
    }
    for key, value in expected.items():
        need(data[key] == value, "P2_POLICY_UNAPPROVED", f"{key} must be explicit proposed policy")
    identity(data["agreement_id"], "agreement_id")
    for key, maximum in (("investors", 100), ("classes", 30), ("contributions", 2000), ("stages", 100)):
        need(type(data[key]) is list and 0 < len(data[key]) <= maximum,
             "P2_SCHEMA_INVALID", f"{key} must be a bounded nonempty array")
    classes = []
    for row in data["classes"]:
        shape(row, _CLASS_FIELDS, label="class")
        rate = row["preferred_rate_pa"]
        if rate is not None:
            rate = dec(rate, "preferred_rate_pa")
            need(rate < 1, "P2_RATE_INVALID", "annual rate must be below 100%")
        classes.append(EquityClass(identity(row["id"], "class_id"), rate))
    by_class = {c.id: c for c in classes}
    need(len(by_class) == len(classes), "P2_CLASS_DUPLICATE", "repeated equity class")
    investors = []
    for row in data["investors"]:
        shape(row, _INVESTOR_FIELDS, label="investor")
        iid = identity(row["id"], "investor_id")
        cid = identity(row["class_id"], "investor class")
        need(cid in by_class, "P2_CLASS_UNDECLARED", cid)
        share = dec(row["ownership_fraction"], "ownership_fraction")
        need(share <= 1, "P2_OWNERSHIP_INVALID", iid)
        investors.append(Investor(iid, cid, share, dec(row["commitment_keur"], "commitment")))
    by_investor = {i.id: i for i in investors}
    need(len(by_investor) == len(investors), "P2_INVESTOR_DUPLICATE", "duplicate IDs")
    need(sum((i.ownership for i in investors), Decimal(0)) == 1,
         "P2_OWNERSHIP_INVALID", "legal equity fractions must add to exactly one")
    need(all(any(i.class_id == c.id for i in investors) for c in classes),
         "P2_CLASS_EMPTY", "equity classes require explicitly identified holders")
    contributions = []
    for row in data["contributions"]:
        shape(row, _CONTRIBUTION_FIELDS, label="contribution")
        iid = identity(row["investor_id"], "contribution investor")
        need(iid in by_investor, "P2_INVESTOR_UNDECLARED", iid)
        contributions.append(Contribution(iid, dte(row["date"], "contribution date"),
                                          dec(row["amount_keur"], "contribution", positive=True)))
    for investor in investors:
        used = sum((c.amount for c in contributions if c.investor_id == investor.id), Decimal(0))
        need(used <= investor.commitment, "P2_COMMITMENT_EXCEEDED", investor.id)
    stages = []
    for row in data["stages"]:
        shape(row, _STAGE_FIELDS, label="stage")
        kind = row["kind"]
        need(type(kind) is str and kind in _ALLOWED_KINDS, "P2_STAGE_UNSUPPORTED", str(kind))
        cid, bid = row["class_id"], row["beneficiary_id"]
        if kind in ("RETURN_OF_CAPITAL", "PREFERRED_RETURN"):
            need(type(cid) is str and cid in by_class and bid is None and row["lifetime_cap_keur"] is None
                 and row["fraction"] is None, "P2_STAGE_INVALID", kind)
            if kind == "PREFERRED_RETURN":
                need(by_class[cid].preferred_rate is not None, "P2_PREFERENCE_INCOMPLETE", cid)
        elif kind == "CATCH_UP":
            need(cid is None and type(bid) is str and bid in by_investor and row["fraction"] is None,
                 "P2_STAGE_INVALID", "catch-up requires explicit beneficiary and cap")
        elif kind == "CARRY":
            need(cid is None and type(bid) is str and bid in by_investor and row["lifetime_cap_keur"] is None,
                 "P2_STAGE_INVALID", "carry requires explicit beneficiary and fraction")
        else:
            need(cid is None and bid is None and row["lifetime_cap_keur"] is None and row["fraction"] is None,
                 "P2_STAGE_INVALID", "residual allocation is via explicit legal ownership")
        cap = dec(row["lifetime_cap_keur"], "lifetime cap") if kind == "CATCH_UP" else None
        frac = dec(row["fraction"], "carry fraction") if kind == "CARRY" else None
        if kind == "CATCH_UP":
            need(cap > 0, "P2_CATCHUP_INCOMPLETE", "positive lifetime cap required")
        if kind == "CARRY":
            need(frac > 0 and frac < 1, "P2_CARRY_INCOMPLETE", "fraction strictly between 0 and 1")
        stages.append(Stage(kind, cid, bid, cap, frac))
    need(stages[-1].kind == "RESIDUAL" and sum(s.kind == "RESIDUAL" for s in stages) == 1,
         "P2_RESIDUAL_INVALID", "exactly one final residual stage is required")
    need(len({(s.kind, s.class_id, s.beneficiary_id) for s in stages}) == len(stages),
         "P2_STAGE_DUPLICATE", "duplicate entitlement stage")
    for c in classes:
        if c.preferred_rate is not None:
            need(any(s.kind == "PREFERRED_RETURN" and s.class_id == c.id for s in stages),
                 "P2_PREFERENCE_INCOMPLETE", c.id)
    # Stage order is CONTRACT ORDER, not a model-wide preferred legal waterfall.
    document = canonical(data)
    return Contract(data["agreement_id"], data["version"], tuple(sorted(investors, key=lambda i:i.id)),
                    tuple(sorted(classes, key=lambda c:c.id)),
                    tuple(sorted(contributions, key=lambda c:(c.when,c.investor_id,c.amount))),
                    tuple(stages), sha256(document.encode()).hexdigest(), document)
