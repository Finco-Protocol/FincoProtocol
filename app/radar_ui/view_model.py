"""Presentation-only view models for the Radar v1 UI (P8/P9/P6).

Rules enforced by construction:

- the view model FORMATS only — it extracts and labels values that the
  frozen R0–R12 authority (preserved verbatim in the P1 snapshot) already
  produced.  It never calculates a market price, never derives GAP,
  never infers availability, never redefines freshness, never reinterprets
  verification and never substitutes fallback estimates.
- every section degrades to an explicit UNAVAILABLE state; a partial or
  unavailable snapshot remains fully renderable and inspectable.
- the Evidence Inspector reveals lineage for a displayed field strictly
  from the SAME immutable snapshot — NUMBER → SOURCE → DERIVATION →
  LINEAGE → EVIDENCE → VERIFICATION — and reports UNAVAILABLE where
  lineage does not genuinely exist.
"""
from __future__ import annotations

from typing import Any, Mapping

from app.radar_runtime.contracts import canonical_sha256

PROVIDER_NAME = "radar-core"

_READ_ONLY_NOTICE = "READ-ONLY — quote direction only; no transaction submission"


def _provider_result(payload: Mapping[str, Any],
                     name: str = PROVIDER_NAME) -> "Mapping[str, Any] | None":
    for result in payload.get("providers", []):
        if result.get("provider") == name:
            return result
    return None


def _section(evidence: Mapping[str, Any], key: str) -> dict[str, Any]:
    section = evidence.get(key)
    if not isinstance(section, Mapping) or section.get("available") is not True:
        reason = None
        if isinstance(section, Mapping):
            reason = section.get("reason")
        return {"available": False,
                "reason": reason or "NOT_PROVIDED_BY_ACQUISITION",
                "fields": {}}
    return {"available": True, "reason": None,
            "fields": {k: v for k, v in section.items()
                       if k != "available"}}


def _acquisition_state_label(state: str) -> str:
    return {
        "COMPLETE": "COMPLETE — all providers succeeded",
        "PARTIAL": "PARTIAL — some providers failed; failed sources "
                   "are explicit",
        "UNAVAILABLE": "UNAVAILABLE — no provider succeeded",
    }.get(state, state)


def build_radar_view(snapshot) -> dict[str, Any]:
    """Build the complete panel view model from ONE immutable snapshot."""
    payload = snapshot.to_payload()
    provider = _provider_result(payload)
    evidence: Mapping[str, Any] = (
        provider.get("evidence") if provider is not None else None) or {}
    request = payload.get("request", {})

    reference = _section(evidence, "reference")
    execution = _section(evidence, "execution")
    gap = _section(evidence, "gap")

    return {
        "snapshot_id": snapshot.snapshot_id,
        "state": payload.get("state"),
        "state_label": _acquisition_state_label(payload.get("state", "")),
        "startedAt": payload.get("startedAt"),
        "completedAt": payload.get("completedAt"),
        "read_only_notice": _READ_ONLY_NOTICE,
        "identity": {
            "economicAssetUid": payload.get("economicAssetUid"),
            "chainId": payload.get("chainId"),
            "contractAddress": payload.get("contractAddress"),
            "symbol": (evidence.get("asset") or {}).get("symbol"),
        },
        "request": {
            "direction": request.get("direction"),
            "notionalUsd": request.get("notionalUsd"),
        },
        "reference": {
            **reference,
            "phase": "R2/R7 — frozen bound-reference authority",
        },
        "execution": {
            **execution,
            "phase": "R0 — frozen execution-quote authority",
        },
        "gap": {
            **gap,
            "phase": "R2 — frozen directional GAP authority",
        },
        "freshness": {
            "referenceObservedAt": reference["fields"].get("observedAt"),
            "quoteTime": execution["fields"].get("quotedAt"),
            "gapQuotedAt": gap["fields"].get("quotedAt"),
            "completedAt": payload.get("completedAt"),
            "notice": "each panel shows its OWN source time; availability "
                      "states are independent and never collapsed",
        },
        "providers": [
            {"provider": p.get("provider"),
             "state": p.get("state"),
             "errorClass": p.get("errorClass"),
             "elapsedMs": p.get("elapsedMs")}
            for p in payload.get("providers", [])
        ],
    }


# --------------------------------------------------------------------------
# Evidence Inspector (P6)
# --------------------------------------------------------------------------

def _inspector_common(snapshot, provider_result: "Mapping[str, Any] | None") -> dict[str, Any]:
    payload = snapshot.to_payload()
    return {
        "snapshotId": snapshot.snapshot_id,
        "requestFingerprint": payload.get("requestFingerprint"),
        "provider": (provider_result or {}).get("provider"),
        "providerState": (provider_result or {}).get("state"),
        "observedAt": (provider_result or {}).get("observedAt"),
        "evidenceDigest": (
            "sha256:" + canonical_sha256(provider_result.get("evidence"))
            if provider_result is not None
            and provider_result.get("evidence") is not None else None),
        # Verification is shown only when genuinely available.  The P1
        # acquisition snapshot does not carry R11 verification, so the
        # honest inspector answer is UNAVAILABLE — never invented.
        "verification": {
            "state": "UNAVAILABLE",
            "reason": "R11 verification authority is not part of the P1 "
                      "acquisition snapshot",
        },
    }


def _lineage_rows(snapshot, provider_result: "Mapping[str, Any] | None") -> list[dict[str, str]]:
    payload = snapshot.to_payload()
    rows = [
        {"stage": "LINEAGE",
         "label": "acquisition snapshot",
         "value": snapshot.snapshot_id},
        {"stage": "LINEAGE",
         "label": "request fingerprint",
         "value": str(payload.get("requestFingerprint"))},
        {"stage": "LINEAGE",
         "label": "provider observation",
         "value": f"{(provider_result or {}).get('provider')} "
                  f"[{(provider_result or {}).get('state')}]"
                  f" at {(provider_result or {}).get('observedAt')}"},
    ]
    return rows


def build_inspector_view(snapshot, field_id: str) -> "dict[str, Any] | None":
    """Build the Evidence Inspector view for one displayed field, strictly
    from the referenced immutable snapshot.  Returns None for unknown
    fields (the router renders a typed not-found state)."""
    payload = snapshot.to_payload()
    provider_result = _provider_result(payload)
    evidence: Mapping[str, Any] = (
        provider_result.get("evidence") if provider_result is not None
        else None) or {}
    common = _inspector_common(snapshot, provider_result)

    sections = {
        "reference": _section(evidence, "reference"),
        "execution": _section(evidence, "execution"),
        "gap": _section(evidence, "gap"),
    }
    field_labels = {
        "reference.price": ("Reference price (token midpoint)",
                            "R2/R7 — frozen bound-reference authority",
                            "reference", "price",
                            "official USD price × registry multiplier, "
                            "applied exactly once by the frozen engine"),
        "reference.bid": ("Reference bid (token)",
                          "R2/R7 — frozen bound-reference authority",
                          "reference", "bid",
                          "multiplier-adjusted official BID side"),
        "reference.ask": ("Reference ask (token)",
                          "R2/R7 — frozen bound-reference authority",
                          "reference", "ask",
                          "multiplier-adjusted official ASK side"),
        "execution.status": ("Execution quote status",
                             "R0 — frozen execution-quote authority",
                             "execution", "status",
                             "frozen LI.FI quote adapter status vocabulary"),
        "execution.rawAmountOut": ("Expected output (raw)",
                                   "R0 — frozen execution-quote authority",
                                   "execution", "rawAmountOut",
                                   "provider raw amount, preserved verbatim"),
        "execution.effectivePrice": ("Effective price (USD per token)",
                                     "R0 — frozen execution-quote authority",
                                     "execution", "effectivePrice",
                                     "authority-provided execution price"),
        "gap.gapBps": ("Directional GAP (bps)",
                       "R2 — frozen directional GAP authority",
                       "gap", "gapBps",
                       "signed on-chain execution price vs the economically "
                       "matching frozen reference side"),
        "gap.gapToMidBps": ("GAP to midpoint (bps, neutral)",
                            "R2 — frozen directional GAP authority",
                            "gap", "gapToMidBps",
                            "neutral midpoint comparison; not a trading "
                            "signal"),
        "snapshot.state": ("Acquisition state",
                           "P1 — acquisition runtime",
                           None, None,
                           "runtime acquisition completeness only"),
    }
    if field_id not in field_labels:
        return None
    label, phase, section_key, value_key, derivation = field_labels[field_id]

    # NUMBER
    if section_key is None:
        value = payload.get("state")
        available = True
        reason = None
    else:
        section = sections[section_key]
        available = section["available"]
        reason = section["reason"]
        value = section["fields"].get(value_key)

    gaps: list[dict[str, str]] = []
    if not available:
        gaps.append({"gapKind": "SECTION_UNAVAILABLE",
                     "reason": reason or "NOT_PROVIDED_BY_ACQUISITION"})

    return {
        "field": field_id,
        "label": label,
        "number": {"value": value, "available": available},
        "source": {
            "provider": common["provider"],
            "providerState": common["providerState"],
            "phase": phase,
            "observedAt": common["observedAt"],
        },
        "derivation": derivation,
        "lineage": _lineage_rows(snapshot, provider_result),
        "evidence": {
            "digest": common["evidenceDigest"],
            "providerPayload": (provider_result or {}).get("evidence"),
        },
        "verification": common["verification"],
        "gaps": gaps,
        "snapshotId": common["snapshotId"],
        "requestFingerprint": common["requestFingerprint"],
        "readOnly": _READ_ONLY_NOTICE,
    }
