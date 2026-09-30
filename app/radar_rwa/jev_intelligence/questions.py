"""Typed System One questions (V1) and strict response validation.

Included: ``market_regime`` (Choice) and ``attention`` (Score). Deliberately NOT included:
- a persistence/"likely to persist" Noul: no immutable outcome policy or baseline exists yet;
- a movement-quality Choice: FINCO holds no wallet-flow or trade-level evidence, only a
  premium series, so an ORGANIC/ABRUPT distinction would not be evidence-backed.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping

from .contracts import (ATTENTION_LEVELS, QUESTION_IDS, REGIME_OPTIONS, AttentionAnswer,
                        FeatureState, RegimeAnswer)

_COMMON = (
    "The state is a set of closed-vocabulary buckets describing the premium/discount series "
    "of an on-chain token reference versus a source-bound equity basis. Judge only the "
    "supplied buckets. UNAVAILABLE means unknown, never zero. Do not infer asset identity, "
    "recompute any number, or produce investment advice."
)

REGIME_DESCRIPTIONS = {
    "MOMENTUM": "Recent premium movement is directionally persistent across the short and long windows.",
    "MEAN_REVERTING": "The premium sits at the edge of its range and short and long movement point in opposite directions.",
    "RANGE_BOUND": "The premium is oscillating inside a stable range without a clear direction.",
    "UNRESOLVED": "The buckets do not support a defensible regime judgement.",
}


def build_request(state: FeatureState, *, model: str) -> dict[str, object]:
    if not model.strip():
        raise ValueError("model must be non-empty")
    return {
        "model": model,
        "state": {
            "feature_schema_version": state.schema_version,
            "input_fingerprint": state.input_fingerprint,
            "features": dict(state.features),
        },
        "questions": {
            "market_regime": {
                "type": "choice",
                "instructions": "Which market regime best describes the premium series? " + _COMMON,
                "options": dict(REGIME_DESCRIPTIONS),
            },
            "attention": {
                "type": "score",
                "instructions": ("How much analyst attention does the current premium state "
                                 "warrant, relative to a normal state? " + _COMMON),
                "legend": list(ATTENTION_LEVELS),
            },
        },
    }


def _probability(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name}_NOT_NUMERIC")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name}_NOT_NUMERIC") from None
    if not parsed.is_finite() or not Decimal(0) <= parsed <= Decimal(1):
        raise ValueError(f"{name}_OUT_OF_BOUNDS")
    return parsed


def _optional_confidence(answer: Mapping[str, object]) -> Decimal | None:
    if "confidence" not in answer or answer["confidence"] is None:
        return None
    return _probability(answer["confidence"], "CONFIDENCE")


def _parse_regime(answer: object) -> RegimeAnswer:
    if not isinstance(answer, Mapping) or answer.get("type", "choice") != "choice":
        raise ValueError("JEV_MARKET_REGIME_ANSWER_INVALID")
    choice = answer.get("choice")
    if choice not in REGIME_OPTIONS:
        raise ValueError("JEV_MARKET_REGIME_CHOICE_UNEXPECTED")
    raw = answer.get("probabilities")
    rows: list[tuple[str, Decimal]] = []
    if raw is not None:
        if not isinstance(raw, Mapping) or not set(raw) <= set(REGIME_OPTIONS):
            raise ValueError("JEV_MARKET_REGIME_PROBABILITIES_INVALID")
        rows = [(key, _probability(raw[key], "PROBABILITY")) for key in REGIME_OPTIONS if key in raw]
        if sum(v for _, v in rows) > Decimal("1.001"):
            raise ValueError("JEV_MARKET_REGIME_PROBABILITIES_EXCEED_ONE")
    return RegimeAnswer(choice=choice, probabilities=tuple(rows), confidence=_optional_confidence(answer))


def _parse_attention(answer: object) -> AttentionAnswer:
    if not isinstance(answer, Mapping) or answer.get("type", "score") != "score":
        raise ValueError("JEV_ATTENTION_ANSWER_INVALID")
    raw = answer.get("score")
    if isinstance(raw, bool):
        raise ValueError("JEV_ATTENTION_SCORE_NOT_NUMERIC")
    try:
        score = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise ValueError("JEV_ATTENTION_SCORE_NOT_NUMERIC") from None
    if not score.is_finite():
        raise ValueError("JEV_ATTENTION_SCORE_NOT_NUMERIC")
    base = 0
    legend = answer.get("legend")
    if legend is not None:
        if not isinstance(legend, Mapping) or not legend:
            raise ValueError("JEV_ATTENTION_LEGEND_INVALID")
        try:
            indexed = sorted((int(k), str(v)) for k, v in legend.items())
        except (TypeError, ValueError):
            raise ValueError("JEV_ATTENTION_LEGEND_INVALID") from None
        if tuple(label for _, label in indexed) != ATTENTION_LEVELS:
            raise ValueError("JEV_ATTENTION_LEGEND_MISMATCH")
        base = indexed[0][0]
    index = int((score - base).to_integral_value(rounding="ROUND_HALF_EVEN"))
    if not 0 <= index < len(ATTENTION_LEVELS) or not (
            Decimal(base) - Decimal("0.5") <= score <= Decimal(base + len(ATTENTION_LEVELS) - 1) + Decimal("0.5")):
        raise ValueError("JEV_ATTENTION_SCORE_OUT_OF_RANGE")
    return AttentionAnswer(state=ATTENTION_LEVELS[index], score=score,
                           confidence=_optional_confidence(answer))


def parse_response(response: Mapping[str, object]) -> tuple[RegimeAnswer, AttentionAnswer, str]:
    """Validate a provider response; raises ValueError with a closed reason code."""
    model = response.get("model")
    answers = response.get("answers")
    if not isinstance(model, str) or not model.strip() or not isinstance(answers, Mapping):
        raise ValueError("JEV_RESPONSE_SHAPE_INVALID")
    if set(answers) != set(QUESTION_IDS):
        raise ValueError("JEV_UNEXPECTED_QUESTION_OUTPUT")
    return _parse_regime(answers["market_regime"]), _parse_attention(answers["attention"]), model
