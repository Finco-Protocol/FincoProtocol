"""Import V2 deterministic mapping candidates.  Explainable ranking, never write authority.

A candidate is EVIDENCE that a source cell may correspond to a FINCO target.  It carries no confidence
probability: only a category derived from stated, inspectable features (token overlap, unit dimension,
sheet context, technology applicability).  Every candidate is re-validated by the exact V1 checks
(registry applicability + unit normalisation + canonical validator) and the user must still approve it.

Targets are classified by who may write them:
  SCALAR            canonical C0 field eligible for the atomic batch writer
  CAPEX_LINE / OPEX_LINE        cost line items (their own identity + atomic cost writer)
  REVENUE_CONTRACT              Revenue V2 versioned contracts (dedicated transaction)
  FINANCING_INSTRUMENT          F3/F3.5 instruments (Financing workspace, activation boundaries)
Non-scalar targets are read-only here: ``UNSUPPORTED_FOR_APPLY`` with the editor that owns them.

No network, no model, no I/O.  An optional external suggestion could only enter through
``validate_candidate`` -- the same checks, no bypass.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any, Iterable

from app.workbook.registry import WORKBOOK
from app.workbook.specs import BindingStatus, FieldKind, FieldType, SourceOfTruth
from app.workbook.update_service import BatchApplyError, _assert_batch_field_applicable

SCALAR, CAPEX_LINE, OPEX_LINE = "SCALAR", "CAPEX_LINE", "OPEX_LINE"
REVENUE_CONTRACT, FINANCING_INSTRUMENT, UNSUPPORTED = "REVENUE_CONTRACT", "FINANCING_INSTRUMENT", "UNSUPPORTED"
UNSUPPORTED_FOR_APPLY = "UNSUPPORTED_FOR_APPLY"

# Fields that exist in the registry but are structured documents, owned by dedicated writers.
STRUCTURED_FIELD_OWNERS = {
    "revenue.multistream.contracts": (REVENUE_CONTRACT, "Revenue contract editor"),
    "revenue.merchant.price_curve_json": (REVENUE_CONTRACT, "Revenue contract editor"),
    "debt.financing.instruments": (FINANCING_INSTRUMENT, "Capital Stack workspace"),
    "debt.bankability.configuration": (FINANCING_INSTRUMENT, "Bankability configuration"),
}
OWNER_TEXT = {
    CAPEX_LINE: "CAPEX sheet (existing line items and atomic cost Save)",
    OPEX_LINE: "OPEX sheet (existing line items and atomic cost Save)",
    REVENUE_CONTRACT: "Revenue contract editor (PPA / Merchant / CfD)",
    FINANCING_INSTRUMENT: "Capital Stack workspace (F3 / F3.5 permissions)",
}
CATEGORY_BY_SHEET = {"capex": "CAPEX", "opex": "OPEX", "revenue": "REVENUE", "debt": "FINANCING", "tax": "TAX",
                     "project_setup": "GENERAL"}
CATEGORIES = ("CAPEX", "OPEX", "REVENUE", "FINANCING", "TAX", "GENERAL")

# Terminology -> canonical token.  Longest phrase first; applied to normalised text.
_PHRASES = (
    ("capital expenditure", "capex"), ("capital expenditures", "capex"), ("operating expenditure", "opex"),
    ("operating expenses", "opex"), ("operating costs", "opex"), ("operation and maintenance", "om"),
    ("operations and maintenance", "om"), ("o and m", "om"), ("installed capacity", "capacity"),
    ("nameplate capacity", "capacity"), ("nominal power", "capacity"), ("plant capacity", "capacity"),
    ("full load hours", "hours"), ("full-load hours", "hours"), ("equivalent full load hours", "hours"),
    ("operating hours", "hours"), ("yield hours", "hours"), ("ppa price", "tariff"), ("ppa tariff", "tariff"),
    ("contracted price", "tariff"), ("feed in tariff", "tariff"), ("power purchase agreement", "ppa"),
    ("cost of debt", "interest rate"), ("all in interest", "interest rate"), ("debt interest", "interest rate"),
    ("senior interest", "interest rate"), ("loan to cost", "gearing"), ("debt ratio", "gearing"),
    ("leverage", "gearing"), ("loan tenor", "tenor"), ("loan term", "tenor"), ("debt tenor", "tenor"),
    ("debt maturity", "tenor"), ("corporate income tax", "cit"), ("corporate tax", "cit"),
    ("income tax rate", "cit"), ("tax losses carried forward", "loss carryforward"),
    ("loss carry forward", "loss carryforward"), ("loss carry-forward", "loss carryforward"),
    ("commissioning date", "cod date"), ("commercial operation date", "cod date"),
    ("start of operation", "cod date"), ("build time", "construction duration"),
    ("construction period", "construction duration"), ("construction time", "construction duration"),
    ("project life", "horizon"), ("project lifetime", "horizon"), ("asset life", "horizon"),
    ("economic life", "horizon"), ("analysis period", "horizon"), ("grid interconnection", "grid connection"),
    ("interconnection", "grid connection"), ("inflation", "index"), ("indexation", "index"),
    ("escalation", "index"), ("per year", "annual"), ("p a", "annual"), ("per annum", "annual"),
    ("service fee", "service price"), ("minimum debt service coverage", "dscr"),
    ("debt service coverage ratio", "dscr"), ("dscr", "dscr"),
)
_STOP = frozenset("the of and a an for to in on at by with per eur keur k assumption assumptions value input".split())
_STEM = {"insurances": "insurance", "taxes": "tax", "fees": "fee", "costs": "cost", "years": "year", "months": "month",
         "prices": "price", "lines": "line", "units": "unit", "contracts": "contract", "hours": "hours"}
_INTENT_OPEX = frozenset({"opex", "annual", "yr", "operating", "om"})
_INTENT_CAPEX = frozenset({"capex", "construction", "development", "oneoff"})

# Structured-target vocabulary (used only when no scalar target is convincing).
_FINANCING_WORDS = frozenset({"junior", "mezzanine", "mezz", "tranche", "facility", "preferred", "subordinated",
                              "pik", "shl", "shareholder", "bond", "refinancing"})
_REVENUE_WORDS = frozenset({"merchant", "cfd", "strike", "capture", "curve", "contract", "ppa", "offtake"})
_COST_LINE_WORDS = frozenset({"epc", "o&m", "om", "lease", "land", "grid", "cabling", "transformer", "inverter",
                              "module", "turbine", "foundation", "insurance", "security", "cleaning", "maintenance",
                              "management", "permit", "legal", "audit", "contingency", "decommissioning"})


def _fold(text: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").casefold()
    raw = raw.replace("&", " and ").replace("%", " pct ")
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def tokens(text: Any) -> frozenset[str]:
    folded = " " + _fold(text) + " "
    for phrase, canon in _PHRASES:
        p = " " + _fold(phrase) + " "
        if p in folded:
            folded = folded.replace(p, " " + canon + " ")
    out = set()
    for tok in folded.split():
        tok = _STEM.get(tok, tok)
        if tok in _STOP or len(tok) < 2:
            continue
        out.add(tok)
    return frozenset(out)


# ── unit dimensions ─────────────────────────────────────────────────────────────────────────
_UNIT_PATTERNS = (
    (r"^(k\s?eur|keur|k€|thousand eur|teur)(/yr|/year|/a| per year| p\.a\.)?$", "currency_k"),
    (r"^(eur|euro|euros|€)(/yr|/year|/a| per year| p\.a\.)?$", "currency"),
    (r"^(eur|€)/mwh$", "price_mwh"), (r"^(eur|€)/kwh$", "price_kwh"), (r"^(eur|€)/kw/month$", "price_kw_month"),
    (r"^(%|pct|percent|percentage|%/yr|%/year)$", "percent"), (r"^(fraction|decimal|ratio)$", "fraction"),
    (r"^mw$", "power_mw"), (r"^kw$", "power_kw"), (r"^gw$", "power_gw"), (r"^(mwp|kwp)$", "power_peak"),
    (r"^(h|h/yr|hours|hours/yr|h/a)$", "hours"), (r"^(year|years|yr|yrs)$", "years"), (r"^(month|months)$", "months"),
    (r"^(date|iso|iso8601)$", "date"), (r"^x$", "multiple"),
)


def unit_dimension(unit: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(unit or "").strip().casefold())
    if not text:
        return None
    for pattern, dim in _UNIT_PATTERNS:
        if re.match(pattern, text):
            return dim
    return "unknown"


_DIM_FAMILY = {"currency": "currency", "currency_k": "currency", "price_mwh": "price", "price_kwh": "price",
               "price_kw_month": "price_kw_month", "percent": "rate", "fraction": "rate", "power_mw": "power",
               "power_kw": "power", "power_gw": "power", "power_peak": "power_peak", "hours": "hours",
               "years": "years", "months": "months", "date": "date", "multiple": "multiple"}


def field_family(spec) -> str:
    ft, unit = spec.field_type, (spec.unit or "").casefold()
    return {FieldType.KEUR: "currency", FieldType.PCT: "rate", FieldType.MW: "power", FieldType.MWH: "hours",
            FieldType.YEARS: "years", FieldType.MONTHS: "months", FieldType.DATE: "date", FieldType.BOOL: "bool",
            FieldType.TEXT: "text", FieldType.SELECT: "text"}.get(ft) or (
        "price" if unit.startswith("eur/") and "month" not in unit else
        "price_kw_month" if "month" in unit else "multiple" if unit in ("x", "ratio") else "number")


def source_unit_from_label(label: str) -> tuple[str | None, str]:
    """Explicit unit written in the label itself, e.g. ``Installed capacity (MW)`` / ``[kEUR]``."""
    match = re.search(r"[\(\[]\s*([^()\[\]]{1,16}?)\s*[\)\]]\s*$", label or "")
    if match and unit_dimension(match.group(1)) not in (None, "unknown"):
        return match.group(1).strip(), re.sub(r"\s*[\(\[][^()\[\]]*[\)\]]\s*$", "", label).strip()
    return None, label


# ── candidate model ─────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Candidate:
    kind: str                       # SCALAR / CAPEX_LINE / ... / UNSUPPORTED
    field_id: str | None
    label: str
    category: str
    confidence: str                 # exact / high / medium / low / none
    score: float
    explanation: tuple[str, ...]
    applyable: bool
    owner: str | None = None        # editor that owns a non-scalar target

    def as_dict(self) -> dict:
        return {"kind": self.kind, "field_id": self.field_id, "label": self.label, "category": self.category,
                "confidence": self.confidence, "score": round(self.score, 3), "explanation": list(self.explanation),
                "applyable": self.applyable, "owner": self.owner}


def _eligible(spec) -> bool:
    return (spec.binding_status == BindingStatus.BOUND and spec.kind == FieldKind.INPUT
            and spec.source_of_truth == SourceOfTruth.INPUT_SET and spec.editable and spec.persisted
            and not spec.runtime_only)


_CACHE: dict[str, Any] = {}


def _index():
    if "v" not in _CACHE:
        rows = []
        for spec in WORKBOOK.all_fields():
            if not _eligible(spec):
                continue
            rows.append((spec, tokens(spec.label + " " + spec.section_id.replace("_", " ")), tokens(spec.label)))
        _CACHE["v"] = rows
    return _CACHE["v"]


def _applicable(field_id: str, project_type: str, template_source: str) -> bool:
    return _applicability(field_id, project_type, template_source) == "OK"


def _applicability(field_id: str, project_type: str, template_source: str) -> str:
    try:
        _assert_batch_field_applicable(field_id, project_type=project_type, template_source=template_source)
        return "OK"
    except BatchApplyError as exc:
        return getattr(exc, "code", "BATCH_FIELD_NOT_APPLICABLE")


def _intent(label_tokens: frozenset[str], unit: Any, section: str) -> str | None:
    text = tokens(section) | label_tokens
    unit_text = str(unit or "").casefold()
    if "/yr" in unit_text or "per year" in unit_text or text & _INTENT_OPEX:
        return "OPEX" if not text & _INTENT_CAPEX else None
    if text & _INTENT_CAPEX:
        return "CAPEX"
    return None


def rank_candidates(*, label: str, unit: str | None, sheet: str = "", section: str = "",
                    project_type: str, template_source: str, limit: int = 3) -> list[Candidate]:
    """Deterministic ranking of FINCO targets for one source cell (best first, ties broken by field id)."""
    explicit_unit, bare_label = source_unit_from_label(label)
    effective_unit = unit or explicit_unit
    src_dim = unit_dimension(effective_unit)
    src_family = _DIM_FAMILY.get(src_dim or "")
    src_tokens = tokens(bare_label)
    context_tokens = tokens(sheet) | tokens(section)
    intent = _intent(src_tokens, effective_unit, section or sheet)
    scored: list[Candidate] = []
    dices: dict[str, float] = {}
    if not src_tokens:
        return []
    for spec, full_tokens, label_tokens in _index():
        if spec.field_id in STRUCTURED_FIELD_OWNERS:
            continue
        reasons: list[str] = []
        common = src_tokens & label_tokens
        if not common:
            continue
        # Dice over the field label: how much of the label is evidenced, and how much source text is explained.
        dice = 2 * len(common) / (len(src_tokens) + len(label_tokens))
        score = dice
        reasons.append("label terms matched: " + ", ".join(sorted(common)))
        category = CATEGORY_BY_SHEET.get(spec.sheet_id, "GENERAL")
        if context_tokens & full_tokens - label_tokens:
            score += 0.05
            reasons.append("sheet/section context agrees")
        if intent and intent == category:
            score += 0.15
            reasons.append(f"{intent.lower()} context")
        elif intent and category in ("CAPEX", "OPEX") and intent != category:
            score -= 0.35
            reasons.append(f"{intent.lower()} wording conflicts with a {category.lower()} field")
        family = field_family(spec)
        if src_family is not None:
            compatible = src_family == family or (src_family == "price" and family == "price")
            if family == "bool" or family == "text":
                compatible = False
            if not compatible:
                continue                    # dimensionally incompatible: never a candidate
            score += 0.1
            reasons.append(f"unit dimension compatible ({effective_unit})")
        elif src_dim == "unknown":
            continue
        else:
            reasons.append("source unit not stated; the user must supply it before Apply")
        verdict = _applicability(spec.field_id, project_type, template_source)
        if verdict == "BATCH_FIELD_REQUIRES_ATOMIC_CASCADE_SUPPORT":
            # Recognised, but the atomic batch writer cannot apply it yet: surface it honestly, never write it.
            reasons.append("recognised, but the C0 batch writer cannot apply this field (needs cascade support)")
            scored.append(Candidate(UNSUPPORTED, spec.field_id, spec.label, category, "low", min(score, 0.99),
                                    tuple(reasons), False, "Inputs workspace (cascade-aware field editor)"))
            dices[spec.field_id] = dice
            continue
        if verdict != "OK":
            continue
        dices[spec.field_id] = dice
        scored.append(Candidate(SCALAR, spec.field_id, spec.label, category, "low", min(score, 0.99),
                                tuple(reasons), True))
    scored.sort(key=lambda c: (-c.score, c.field_id))
    ranked: list[Candidate] = []
    for i, cand in enumerate(scored[: max(limit, 1)]):
        margin = cand.score - (scored[i + 1].score if i + 1 < len(scored) else 0.0)
        pure = dices.get(cand.field_id, 0.0)           # label overlap alone, before context/unit bonuses
        if cand.score >= 0.8 and margin >= 0.15 and pure >= 0.6:
            conf = "high"
        elif cand.score >= 0.55 and margin >= 0.08 and pure >= 0.6:
            conf = "medium"
        else:
            conf = "low"
        reasons = cand.explanation + ((f"top alternative is within {margin:.2f}: ambiguous",) if margin < 0.08 and i == 0 and len(scored) > 1 else ())
        ranked.append(Candidate(cand.kind, cand.field_id, cand.label, cand.category, conf, cand.score, reasons,
                                cand.applyable, cand.owner))
    return ranked


def structured_target(label: str, section: str = "", sheet: str = "") -> Candidate | None:
    """Read-only classification of cells that belong to a non-scalar writer (no field can be forged from it)."""
    t = tokens(label) | tokens(section) | tokens(sheet)
    raw = _fold(label + " " + section + " " + sheet).split()
    words = set(raw) | set(t)
    if words & _FINANCING_WORDS:
        kind, why = FINANCING_INSTRUMENT, "financing instrument terms (" + ", ".join(sorted(words & _FINANCING_WORDS)) + ")"
    elif words & _REVENUE_WORDS and not {"tariff"} & words:
        kind, why = REVENUE_CONTRACT, "revenue contract terms (" + ", ".join(sorted(words & _REVENUE_WORDS)) + ")"
    elif words & {"capex"} or (words & _COST_LINE_WORDS and not words & _INTENT_OPEX):
        kind, why = CAPEX_LINE, "cost line wording without a matching scalar field"
    elif words & _INTENT_OPEX and words & _COST_LINE_WORDS:
        kind, why = OPEX_LINE, "annual cost line wording without a matching scalar field"
    else:
        return None
    category = {CAPEX_LINE: "CAPEX", OPEX_LINE: "OPEX", REVENUE_CONTRACT: "REVENUE", FINANCING_INSTRUMENT: "FINANCING"}[kind]
    return Candidate(kind, None, "", category, "low", 0.0, (why, "read-only: " + OWNER_TEXT[kind]), False, OWNER_TEXT[kind])


def classify_cell(*, label: str, unit: str | None, sheet: str = "", section: str = "",
                  project_type: str, template_source: str) -> dict:
    """Best scalar candidate (if convincing), alternatives, or a structured / unsupported classification."""
    ranked = rank_candidates(label=label, unit=unit, sheet=sheet, section=section,
                             project_type=project_type, template_source=template_source)
    top = ranked[0] if ranked else None
    if top is not None and top.kind == UNSUPPORTED and top.confidence == "low":
        top = None                      # a weak match to a non-applyable field is not worth reporting
    ambiguous = bool(top and top.confidence == "low" and len(ranked) > 1 and top.score - ranked[1].score < 0.08)
    if top is not None and top.confidence in ("high", "medium") and top.kind == UNSUPPORTED:
        return {"target_kind": UNSUPPORTED, "suggestion": top.as_dict(), "alternatives": [c.as_dict() for c in ranked[1:]],
                "category": top.category, "ambiguous": False, "apply_support": UNSUPPORTED_FOR_APPLY}
    if top is not None and top.confidence in ("high", "medium"):
        return {"target_kind": SCALAR, "suggestion": top.as_dict(), "alternatives": [c.as_dict() for c in ranked[1:]],
                "category": top.category, "ambiguous": False, "apply_support": "APPLYABLE"}
    structured = structured_target(label, section, sheet)
    if structured is not None:
        return {"target_kind": structured.kind, "suggestion": structured.as_dict(),
                "alternatives": [c.as_dict() for c in ranked], "category": structured.category,
                "ambiguous": False, "apply_support": UNSUPPORTED_FOR_APPLY}
    return {"target_kind": UNSUPPORTED, "suggestion": None, "alternatives": [c.as_dict() for c in ranked],
            "category": top.category if top else "UNMAPPED", "ambiguous": ambiguous,
            "apply_support": "NONE"}


def validate_candidate(*, field_id: str, project_type: str, template_source: str) -> tuple[bool, str]:
    """Single gate for ANY proposed target (ranker, user choice, or a future opt-in assistant)."""
    if field_id in STRUCTURED_FIELD_OWNERS:
        return False, UNSUPPORTED_FOR_APPLY
    try:
        spec = WORKBOOK.field(field_id)
    except KeyError:
        return False, "IMPORT_UNKNOWN_FIELD"
    if not _eligible(spec):
        return False, "IMPORT_FIELD_NOT_EDITABLE_INPUT"
    verdict = _applicability(field_id, project_type, template_source)
    return (verdict == "OK"), verdict


# ── localized numbers (deterministic; ambiguity is rejected, never guessed) ─────────────────
class NumberFormatError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _grouped(text: str, mark: str) -> bool:
    return re.fullmatch(r"\d{1,3}(?:%s\d{3})+" % re.escape(mark), text) is not None


def parse_localized_number(text: str) -> Decimal:
    """Parse ``1.234,56`` / ``1,234.56`` / ``1 234,5`` / ``12,5`` / ``1234.5`` without locale guessing.

    Rules (anything else is rejected, never guessed):
      * both ``.`` and ``,`` present: the LAST one is the decimal mark, the other must group the whole part in threes;
      * space (or NBSP) grouping: groups of exactly three, and the single remaining ``.``/``,`` is the decimal mark;
      * ``.`` only: one dot is a decimal point (``12.5``, ``0.125``) unless exactly three digits follow a 1-3 digit
        whole part (``18.000``: thousands or decimal?) which is AMBIGUOUS; several dots must be thousands groups;
      * ``,`` only: one comma with exactly three following digits (``1,234``) is AMBIGUOUS; otherwise a decimal
        mark; several commas must be thousands groups.
    """
    raw = (text or "").strip().replace("\u00a0", " ").replace("\u202f", " ")
    sign = ""
    if raw[:1] in ("+", "-"):
        sign, raw = raw[0], raw[1:].strip()
    if not raw or not re.fullmatch(r"[0-9][0-9 .,]*", raw):
        raise NumberFormatError("IMPORT_VALUE_INVALID")
    spaced = " " in raw
    if spaced:
        parts = raw.split(" ")
        tail = re.split(r"[.,]", parts[-1])[0]
        if not (re.fullmatch(r"\d{1,3}", parts[0]) and all(re.fullmatch(r"\d{3}", g) for g in parts[1:-1])
                and re.fullmatch(r"\d{3}", tail) and len(parts) > 1):
            raise NumberFormatError("IMPORT_NUMBER_FORMAT_AMBIGUOUS")
        raw = "".join(parts)
    dots, commas = raw.count("."), raw.count(",")
    try:
        if dots and commas:
            mark = "." if raw.rfind(".") > raw.rfind(",") else ","
            other = "," if mark == "." else "."
            whole, _, frac = raw.rpartition(mark)
            if mark in whole or not _grouped(whole, other) or not frac.isdigit():
                raise NumberFormatError("IMPORT_NUMBER_FORMAT_AMBIGUOUS")
            return Decimal(sign + whole.replace(other, "") + "." + frac)
        if not dots and not commas:
            return Decimal(sign + raw)
        mark = "." if dots else ","
        count = dots or commas
        whole, _, frac = raw.rpartition(mark)
        if count > 1:
            if spaced or not _grouped(raw, mark):
                raise NumberFormatError("IMPORT_NUMBER_FORMAT_AMBIGUOUS")
            return Decimal(sign + raw.replace(mark, ""))
        if not whole.isdigit() or not frac.isdigit():
            raise NumberFormatError("IMPORT_VALUE_INVALID")
        if len(frac) == 3 and not spaced and (mark == "," or re.fullmatch(r"[1-9]\d{0,2}", whole)):
            # "1,234" / "18.000" read as thousands in one convention and as a decimal in the other: a 1000x
            # error either way, so it is never guessed.  ("0.125" is unambiguous: a group cannot start with 0.)
            raise NumberFormatError("IMPORT_NUMBER_FORMAT_AMBIGUOUS")
        return Decimal(sign + whole + "." + frac)
    except InvalidOperation as exc:
        raise NumberFormatError("IMPORT_VALUE_INVALID") from exc


__all__ = ["Candidate", "classify_cell", "rank_candidates", "structured_target", "validate_candidate",
           "parse_localized_number", "NumberFormatError", "source_unit_from_label", "unit_dimension", "tokens",
           "STRUCTURED_FIELD_OWNERS", "UNSUPPORTED_FOR_APPLY", "CATEGORIES", "OWNER_TEXT"]
