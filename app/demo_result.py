"""app.demo_result — presentation-layer run result container (Phase B4).

Moved out of app.ui_runner so the production run path carries no dependency
on the legacy demo funnel module. Pure data container: no engine, no
financial logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DemoResult:
    project_inputs: object | None = None
    result: object | None = None
    portfolio_result: object | None = None
    messages: list[str] = field(default_factory=list)
    project_type: str = ""
    is_portfolio: bool = False
    validation_issues: list = field(default_factory=list)
    integration_status: str = "full"
    integration_note: str | None = None
