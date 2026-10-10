"""Read-only views over the registry and over live repository authorities (WF-10A).

The support matrix and the run-integrity check list are derived from the same modules the
product uses (``app.product_capability`` and ``app.run_integrity.checks``), so these pages
cannot disagree with the product.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Iterable

from app.trust_readiness import registry as R
from app.trust_readiness.contracts import (
    STATUS_LABEL,
    STATUS_MEANING,
    ReadinessItem,
    ReadinessStatus,
)

STATUS_ORDER = (
    ReadinessStatus.IMPLEMENTED_VERIFIED,
    ReadinessStatus.PROPOSED,
    ReadinessStatus.REQUIRES_LEGAL_APPROVAL,
    ReadinessStatus.REQUIRES_OPERATIONAL_CONTROLS,
)


def status_legend() -> list[dict]:
    return [
        {"status": s.value, "label": STATUS_LABEL[s], "meaning": STATUS_MEANING[s]}
        for s in STATUS_ORDER
    ]


def status_counts(items: Iterable[ReadinessItem]) -> dict[str, int]:
    c = Counter(i.status for i in items)
    return {s.value: c.get(s, 0) for s in STATUS_ORDER}


def items_by_area(items: Iterable[ReadinessItem]) -> "OrderedDict[str, list[ReadinessItem]]":
    grouped: "OrderedDict[str, list[ReadinessItem]]" = OrderedDict()
    for area in R.AREA_LABELS:
        grouped[area] = []
    for item in items:
        grouped.setdefault(item.area, []).append(item)
    return OrderedDict((k, v) for k, v in grouped.items() if v)


def items_by_status(items: Iterable[ReadinessItem]) -> "OrderedDict[ReadinessStatus, list[ReadinessItem]]":
    items = list(items)
    return OrderedDict((s, [i for i in items if i.status is s]) for s in STATUS_ORDER)


def support_matrix() -> list[dict]:
    """FINCO Model verticals, taken live from the product capability registry."""
    from app.product_capability import PRODUCT_CAPABILITIES

    rows = []
    for cap in PRODUCT_CAPABILITIES:
        if cap.product_area != "model":
            continue
        rows.append({
            "key": cap.key,
            "name": cap.public_name,
            "status": cap.status.value,
            "reference": cap.reference_available,
            "runnable": cap.runnable,
            "cloneable": cap.cloneable,
            "editable": cap.working_copy_editable,
            "last_run": cap.canonical_last_run,
            "api": cap.api_available,
            "export": cap.export_available,
            "note": cap.status_note,
            "limitations": list(cap.limitations),
        })
    return rows


def unavailable_features() -> list[dict]:
    """What a reader might assume exists but does not today."""
    out = []
    for row in support_matrix():
        if row["status"] != "LIVE":
            what = [label for label, ok in (
                ("running", row["runnable"]), ("cloning", row["cloneable"]),
                ("editing a working copy", row["editable"]),
            ) if not ok]
            out.append({
                "name": row["name"],
                "state": row["status"].replace("_", " ").title(),
                "detail": row["note"] or ("Not available: " + ", ".join(what) + "." if what else ""),
            })
    for item in R.all_items():
        if item.status in (ReadinessStatus.PROPOSED, ReadinessStatus.REQUIRES_OPERATIONAL_CONTROLS):
            out.append({"name": item.title, "state": STATUS_LABEL[item.status], "detail": item.statement})
    return out


def integrity_checks() -> list[dict]:
    """The checks a Last Run is put through, read from the implementation itself.

    Each check is invoked on an empty evidence mapping, which every check answers with
    UNAVAILABLE and its own title. No run data is read.
    """
    from app.run_integrity.checks import CHECKS

    out = []
    for fn in CHECKS:
        result = fn({})
        out.append({"id": result.check_id, "title": result.title})
    return out


def known_gaps_sorted():
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(R.KNOWN_GAPS, key=lambda g: (order[g.severity.value], g.key))


def registry_json() -> dict:
    """Machine-readable form of the whole registry (also exposed at /trust/registry.json)."""
    def item(i: ReadinessItem) -> dict:
        return {"key": i.key, "area": i.area, "title": i.title, "status": i.status.value,
                "statement": i.statement, "limitation": i.limitation,
                "evidence": [{"kind": e.kind.value, "path": e.path} for e in i.evidence]}

    return {
        "reviewed_on": R.REVIEWED_ON,
        "scope": R.SCOPE_STATEMENT,
        "statuses": status_legend(),
        "controls": [item(i) for i in R.CONTROLS],
        "release_checklist": [item(i) for i in R.RELEASE_CHECKLIST],
        "data_stores": [{
            "key": d.key, "category": d.data_category, "store": d.store, "tenant_key": d.tenant_key,
            "contents": d.contents, "may_contain_user_text": d.may_contain_user_text,
            "retention": d.retention_rule, "deletion": d.deletion_path,
            "automatic_deletion": d.automatic_deletion, "status": d.status.value,
            "limitation": d.limitation,
        } for d in R.DATA_STORES],
        "known_gaps": [{
            "key": g.key, "title": g.title, "severity": g.severity.value,
            "statement": g.statement, "recommended_action": g.recommended_action,
        } for g in known_gaps_sorted()],
        "not_claimed": [{"label": n.label, "statement": n.statement} for n in R.NOT_CLAIMED],
        "legal_documents": [{"key": d.key, "title": d.title, "publication_state": d.publication_state,
                             "approval_required": d.approval_required} for d in R.LEGAL_DOCUMENTS],
    }
