from fastapi import APIRouter, HTTPException
from app.api.schemas import RunRequest, RunResponse, KPIs
from app.api.project_runner import run_project
from app.input_schema import ProjectInputsSchema, ValidateRequest, ValidateResponse
from app.input_adapter import build_projectinputs
from pydantic import ValidationError

router = APIRouter()

SUPPORTED_PROJECT_TYPES = {"Solar", "Wind", "BESS", "Solar+BESS", "Wind+BESS", "Portfolio"}
SUPPORTED_SCENARIOS = {"Base", "Downside", "Upside"}
SUPPORTED_PERIOD_VIEWS = {"Semiannual", "Annual"}


def _validate_business_rules(schema: ProjectInputsSchema) -> tuple[list[str], list[str]]:
    """Validate business rules WITHOUT running waterfall.

    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # CAPEX validation — threshold depends on project type
    if schema.capex is not None and schema.capex.total_capex_keur is not None:
        # Typical fixed "other" CAPEX (non-EPC, non-production-units) per MW
        if schema.project_type == "Wind":
            other_keur = 15_000
        else:  # Solar and all others
            other_keur = 10_000
        if schema.capex.total_capex_keur <= other_keur:
            errors.append(
                f"total_capex_keur ({schema.capex.total_capex_keur}) must be greater than "
                f"fixed other CAPEX (~{other_keur} kEUR) for {schema.project_type} projects"
            )

    # Debt validation
    if schema.debt is not None:
        if schema.debt.gearing_pct is not None:
            if schema.debt.gearing_pct > 95:
                errors.append(f"gearing_pct ({schema.debt.gearing_pct}) exceeds maximum 95%")
            elif schema.debt.gearing_pct > 85:
                warnings.append(f"gearing_pct ({schema.debt.gearing_pct}) is very high (>85%)")
        if schema.debt.interest_rate_pct is not None:
            if schema.debt.interest_rate_pct < 2.0:
                warnings.append(f"interest_rate_pct ({schema.debt.interest_rate_pct}) is unusually low (<2%)")
        if schema.debt.target_dscr is not None:
            if schema.debt.target_dscr < 1.0:
                errors.append(f"target_dscr ({schema.debt.target_dscr}) must be >= 1.0")

    # Revenue validation
    if schema.revenue is not None:
        if schema.revenue.tariff_eur_mwh is not None:
            if schema.revenue.tariff_eur_mwh < 10:
                warnings.append(f"tariff ({schema.revenue.tariff_eur_mwh} EUR/MWh) is very low")
            elif schema.revenue.tariff_eur_mwh > 300:
                warnings.append(f"tariff ({schema.revenue.tariff_eur_mwh} EUR/MWh) is very high (>300)")
        if schema.revenue.degradation_pct is not None:
            if schema.revenue.degradation_pct > 1.5:
                warnings.append(f"degradation_pct ({schema.revenue.degradation_pct}%) exceeds typical maximum (1.5%)")

    return errors, warnings


@router.get("/project-types")
async def get_project_types():
    return {"project_types": list(SUPPORTED_PROJECT_TYPES)}


@router.get("/scenarios")
async def get_scenarios():
    return {"scenarios": list(SUPPORTED_SCENARIOS)}


@router.post("/run")
async def post_run(request: RunRequest):
    if request.project_type not in SUPPORTED_PROJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported project_type: {request.project_type}")
    if request.scenario not in SUPPORTED_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unsupported scenario: {request.scenario}")
    if request.period_view not in SUPPORTED_PERIOD_VIEWS:
        raise HTTPException(status_code=400, detail=f"Unsupported period_view: {request.period_view}")

    # BESS/Hybrid/Portfolio guardrails
    if request.project_type in {"BESS", "Solar+BESS", "Wind+BESS"}:
        raise HTTPException(status_code=501, detail=f"{request.project_type} not yet supported via API")
    if request.project_type == "Portfolio":
        raise HTTPException(status_code=501, detail="Portfolio not yet supported via API")

    # ── Enforce project_type / scenario consistency before entering try block ──
    # (so HTTPException is not swallowed by the generic Exception catcher)
    if request.inputs is not None:
        # request.inputs is ProjectInputsSchema (Pydantic model), not dict
        if request.inputs.project_type is not None and request.inputs.project_type != request.project_type:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"inputs.project_type '{request.inputs.project_type}' "
                    f"does not match request.project_type '{request.project_type}'"
                ),
            )
        if request.inputs.scenario is not None and request.inputs.scenario != request.scenario:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"inputs.scenario '{request.inputs.scenario}' "
                    f"does not match request.scenario '{request.scenario}'"
                ),
            )

    try:
        project_inputs_override = None
        if request.inputs is not None:
            project_inputs_override = build_projectinputs(request.inputs)

        result = run_project(request.project_type, request.scenario,
                             request.period_view,
                             project_inputs_override=project_inputs_override)
        return result
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate", response_model=ValidateResponse)
async def post_validate(request: ValidateRequest):
    """Validate custom project inputs without running the model."""
    errors, warnings = _validate_business_rules(request.inputs)
    return ValidateResponse(valid=len(errors) == 0, errors=errors, warnings=warnings)