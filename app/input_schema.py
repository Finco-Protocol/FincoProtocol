"""Project inputs schema — validated DTO for custom project inputs.

Architecture:
  JSON/YAML/API request
       ↓
  ProjectInputsSchema (validation only — no business logic)
       ↓
  input_adapter.build_projectinputs()
       ↓
  existing domain ProjectInputs  (frozen dataclass)
       ↓
  run_demo_project() / waterfall runner

This module is intentionally separate from the domain layer.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Optional


class RevenueInput(BaseModel):
    """Revenue assumptions. All fields optional — defaults come from factory."""
    tariff_eur_mwh: Optional[float] = Field(None, gt=0, description="Feed-in tariff EUR/MWh")
    p50_hours: Optional[float] = Field(None, gt=0, description="P50 annual generation hours")
    degradation_pct: Optional[float] = Field(None, ge=0, le=5, description="Annual degradation %")
    ppa_term_years: Optional[int] = Field(None, gt=0, le=30, description="PPA term in years")


class CapexInput(BaseModel):
    """CAPEX assumptions."""
    total_capex_keur: Optional[float] = Field(None, ge=0, description="Total CAPEX in kEUR")


class OpexInput(BaseModel):
    """OPEX assumptions."""
    opex_y1_keur: Optional[float] = Field(None, ge=0, description="Y1 OPEX in kEUR")
    inflation_pct: Optional[float] = Field(None, ge=0, description="Annual OPEX inflation %")


class DebtInput(BaseModel):
    """Debt / financing assumptions."""
    gearing_pct: Optional[float] = Field(None, ge=0, le=100, description="Gearing ratio %")
    senior_debt_keur: Optional[float] = Field(None, ge=0, description="Senior debt override in kEUR")
    interest_rate_pct: Optional[float] = Field(None, gt=0, description="All-in interest rate %")
    tenor_years: Optional[int] = Field(None, gt=0, description="Debt tenor in years")
    target_dscr: Optional[float] = Field(None, gt=0, description="Target DSCR")


class TaxInput(BaseModel):
    """Tax assumptions."""
    cit_rate_pct: Optional[float] = Field(None, ge=0, le=100, description="CIT rate %")
    loss_carryforward_years: Optional[int] = Field(None, ge=0, le=30, description="Loss carryforward years")


class ProjectInputsSchema(BaseModel):
    """Root input schema for custom project definitions.

    All fields are optional — unspecified fields inherit factory defaults.
    The adapter layer (input_adapter.py) merges this schema with factory defaults.

    Phase S1: the schema accepts the SAME set of optional
    input fields as the user-project snapshot dict. This
    means the form path and the snapshot path can produce
    identical ProjectInputs for identical user inputs
    (the S1 unified-resolver contract). Old form-path
    callers that pass only the nested objects continue
    to work (backward compatible).
    """
    project_type: str = "Solar"
    project_name: Optional[str] = None
    scenario: str = "Base"
    # ── Info / identity (Phase S1) ─────────────────────────
    country_iso: Optional[str] = Field(None, description="Country ISO code")
    cod_date: Optional[str] = Field(None, description="ISO date string YYYY-MM-DD")
    construction_months: Optional[int] = Field(None, gt=0, description="Construction period in months")
    horizon_years: Optional[int] = Field(None, gt=0, description="Project horizon in years")
    # ── Technical (Phase S1) ──────────────────────────────
    capacity_mw: Optional[float] = Field(None, gt=0, description="Capacity in MW")
    operating_hours_p90_10y: Optional[float] = Field(None, gt=0, description="P90 10y operating hours")
    operating_hours_p99_1y: Optional[float] = Field(None, gt=0, description="P99 1y operating hours")
    # ── Nested legacy groups (backward compat) ───────────
    revenue: Optional[RevenueInput] = None
    capex: Optional[CapexInput] = None
    opex: Optional[OpexInput] = None
    debt: Optional[DebtInput] = None
    tax: Optional[TaxInput] = None

    @field_validator('project_type')
    @classmethod
    def project_type_valid(cls, v: str) -> str:
        if v not in ("Solar", "Wind", "Storage", "BESS", "Data Center"):
            raise ValueError(f"project_type must be Solar, Wind, Storage, BESS, or Data Center, got '{v}'")
        return v

    @field_validator('scenario')
    @classmethod
    def scenario_valid(cls, v: str) -> str:
        if v not in ("Base", "Downside", "Upside"):
            raise ValueError(f"scenario must be Base, Downside, or Upside, got '{v}'")
        return v


class ValidateRequest(BaseModel):
    """API request body for /validate endpoint."""
    inputs: ProjectInputsSchema


class ValidateResponse(BaseModel):
    """API response body for /validate endpoint."""
    valid: bool
    errors: list[str]
    warnings: list[str] = []
