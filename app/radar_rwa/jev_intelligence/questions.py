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
            # TypeSafe System One request contract: Choice and Score both take ``criteria``
            # (Choice: mapping label -> description; Score: ordered list of levels). ``options``
            # and ``legend`` are not request fields (``legend`` is a Score RESPONSE field).
            "market_regime": {
                "type": "choice",
                "instructions": "Which market regime best describes the premium series? " + _COMMON,
                "criteria": dict(REGIME_DESCRIPTIONS),
            },
            "attention": {
                "type": "score",
                "instructions": ("How much analyst attention does the current premium state "
                                 "warrant, relative to a normal state? " + _COMMON),
                "criteria": list(ATTENTION_LEVELS),
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


def _required_confidence(answer: Mapping[str, object]) -> Decimal:
    if "confidence" not in answer or answer["confidence"] is None:
        raise ValueError("CONFIDENCE_MISSING")
    return _probability(answer["confidence"], "CONFIDENCE")


def _probability_map(raw: object, allowed: set[str], *, code: str) -> tuple[tuple[str, Decimal], ...]:
    if not isinstance(raw, Mapping) or not raw or not {str(k) for k in raw} <= allowed:
        raise ValueError(code)
    rows = tuple((str(k), _probability(v, "PROBABILITY")) for k, v in raw.items())
    if sum(v for _, v in rows) > Decimal("1.001"):
        raise ValueError(f"{code}_EXCEED_ONE")
    return rows


def _parse_regime(answer: object) -> RegimeAnswer:
    if not isinstance(answer, Mapping) or answer.get("type") != "choice":
        raise ValueError("JEV_MARKET_REGIME_ANSWER_INVALID")
    choice = answer.get("choice")
    if choice not in REGIME_OPTIONS:
        raise ValueError("JEV_MARKET_REGIME_CHOICE_UNEXPECTED")
    if "probabilities" not in answer:
        raise ValueError("JEV_MARKET_REGIME_PROBABILITIES_MISSING")
    rows = _probability_map(answer["probabilities"], set(REGIME_OPTIONS),
                            code="JEV_MARKET_REGIME_PROBABILITIES_INVALID")
    ordered = tuple((k, v) for k in REGIME_OPTIONS for kk, v in rows if kk == k)
    if choice not in {k for k, _ in ordered}:
        raise ValueError("JEV_MARKET_REGIME_CHOICE_WITHOUT_PROBABILITY")
    return RegimeAnswer(choice=choice, probabilities=ordered, confidence=_required_confidence(answer))


# Score -> level policy (explicit, deterministic): the provider score is a probability-weighted
# mean of 0-based level indices, so it must lie in [0, len(levels) - 1]. The level is the nearest
# index with exact .5 boundaries rounded UP (ROUND_HALF_UP, i.e. towards higher attention):
# 0.4999 -> NORMAL, 0.5 -> ELEVATED, 1.4999 -> ELEVATED, 1.5 -> HIGH, 2.0 -> HIGH.
SCORE_ROUNDING = "ROUND_HALF_UP"
_EXPECTED_LEGEND = {str(i): label for i, label in enumerate(ATTENTION_LEVELS)}


def score_to_level(score: Decimal) -> str:
    top = Decimal(len(ATTENTION_LEVELS) - 1)
    if not score.is_finite() or score < 0 or score > top:
        raise ValueError("JEV_ATTENTION_SCORE_OUT_OF_RANGE")
    return ATTENTION_LEVELS[int(score.to_integral_value(rounding=SCORE_ROUNDING))]


def _parse_attention(answer: object) -> AttentionAnswer:
    if not isinstance(answer, Mapping) or answer.get("type") != "score":
        raise ValueError("JEV_ATTENTION_ANSWER_INVALID")
    raw = answer.get("score")
    if isinstance(raw, bool):
        raise ValueError("JEV_ATTENTION_SCORE_NOT_NUMERIC")
    try:
        score = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise ValueError("JEV_ATTENTION_SCORE_NOT_NUMERIC") from None
    legend = answer.get("legend")
    if not isinstance(legend, Mapping) or {str(k): str(v) for k, v in legend.items()} != _EXPECTED_LEGEND:
        raise ValueError("JEV_ATTENTION_LEGEND_INVALID")
    level = score_to_level(score)
    if "probabilities" not in answer:
        raise ValueError("JEV_ATTENTION_PROBABILITIES_MISSING")
    _probability_map(answer["probabilities"], set(_EXPECTED_LEGEND) | set(ATTENTION_LEVELS),
                     code="JEV_ATTENTION_PROBABILITIES_INVALID")
    return AttentionAnswer(state=level, score=score, confidence=_required_confidence(answer))


def parse_response(response: Mapping[str, object]) -> tuple[RegimeAnswer, AttentionAnswer, str]:
    """Validate a provider response; raises ValueError with a closed reason code."""
    model = response.get("model")
    answers = response.get("answers")
    if not isinstance(model, str) or not model.strip() or not isinstance(answers, Mapping):
        raise ValueError("JEV_RESPONSE_SHAPE_INVALID")
    if set(answers) != set(QUESTION_IDS):
        raise ValueError("JEV_UNEXPECTED_QUESTION_OUTPUT")
    return _parse_regime(answers["market_regime"]), _parse_attention(answers["attention"]), model
