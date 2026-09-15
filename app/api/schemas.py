from pydantic import BaseModel
from typing import Optional

from app.input_schema import ProjectInputsSchema


class RunRequest(BaseModel):
    project_type: str
    scenario: str
    period_view: str = "Semiannual"
    inputs: Optional[ProjectInputsSchema] = None  #: Custom project inputs (optional, replaces factory defaults)


class KPIs(BaseModel):
    total_revenue_keur: Optional[float] = None
    total_ebitda_keur: Optional[float] = None
    project_irr: Optional[float] = None
    equity_irr: Optional[float] = None
    min_dscr: Optional[float] = None
    avg_dscr: Optional[float] = None


class RunResponse(BaseModel):
    project_type: str
    scenario: str
    period_view: str
    integration_status: str
    integration_note: Optional[str] = None
    messages: list[str]
    kpis: KPIs
    tables: dict