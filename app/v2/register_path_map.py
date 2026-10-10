"""app.v2.register_path_map — proven workbook field-id -> Assumption Register path mapping.

Presentation-only.  The workbook registry (``app.workbook.registry.WORKBOOK``) declares, per
``FieldSpec``, the canonical engine input path (``engine_path``).  The Assumption Register
(``app.model_v2.assumption_register``) identifies each assumption by that same canonical path.
A workbook row is associated with a register path ONLY by exact equality of the two strings and
only when the declaring field is the single registry field that claims that path.  There is no
fuzzy, suffix or label matching; an absent or ambiguous claim yields ``None``.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=1)
def _field_to_register_path() -> dict[str, str]:
    from app.workbook.registry import WORKBOOK

    specs = [f for sheet in WORKBOOK.sheets for section in sheet.sections for f in section.fields]
    claims = Counter(f.engine_path for f in specs if f.engine_path)
    return {
        f.field_id: f.engine_path
        for f in specs
        if f.engine_path and claims[f.engine_path] == 1
    }


def register_path_for_field(field_id: str) -> Optional[str]:
    """Exact canonical Assumption Register path for a workbook field id, or None."""
    return _field_to_register_path().get(str(field_id or ""))


__all__ = ["register_path_for_field"]
