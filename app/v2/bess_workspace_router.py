"""Integrated native BESS editing, using the existing transactional contract writer."""
from datetime import date
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.auth import resolve_request_session, generate_csrf_token, validate_csrf_token
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.persistence.scenarios_repository import get_scenario
from app.ui.protected_reference_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
from app.workbook import bess_config
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get
from app.v2.bess_candidate_router import templates, MAX_REQUEST_BYTES

router = APIRouter()


@router.post('/workbook/bess/working-copy')
async def working_copy(request: Request, _: None = Depends(require_v2_active)):
    if not bess_config.ACTIVATION_ENABLED:
        return JSONResponse({'error': 'BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED'}, status_code=404)
    try:
        form = await request.form()
        if set(form) != {'project', 'csrf_token'}:
            raise ValueError('BESS_CLONE_FORM_SCHEMA')
        user, record, owner = scope(request, str(form['project']))
        if not validate_csrf_token(str(form['csrf_token'])):
            return JSONResponse({'error': 'BESS_CSRF_INVALID'}, status_code=403)
        from app.services.project_library_service import create_working_copy
        copy = create_working_copy(user.user_id, record.project_id)
        from urllib.parse import quote
        return RedirectResponse('/v2/workbook?project=' + quote(copy.project_code), status_code=303)
    except PermissionError as exc:
        return JSONResponse({'error': str(exc)}, status_code=401)
    except LookupError as exc:
        return JSONResponse({'error': str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=409)


def scope(request, project):
    if not bess_config.ACTIVATION_ENABLED:
        raise ValueError("BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED")
    user = resolve_request_session(request)
    if user is None:
        raise PermissionError("Unauthenticated")
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or (record.project_type or "").lower() != "storage":
        raise LookupError("BESS_STANDALONE_SCOPE_REQUIRED")
    return user, record, owner


@router.get('/workbook/bess/inputs', response_class=HTMLResponse)
async def inputs(request: Request, project: str, _: None = Depends(require_v2_active)):
    try:
        user, record, owner = scope(request, project)
        ws = get_workspace_state(owner, record.project_id)
        if ws is None:
            raise LookupError("Workspace unavailable")
        raw = (ws.draft_snapshot or {}).get(bess_config.SNAPSHOT_KEY)
        selected = get_scenario(ws.active_scenario_id, owner) if ws.active_scenario_id else None
        if selected is not None and selected.project_id == ws.project_id and not selected.archived:
            raw = (selected.overrides or {}).get(bess_config.SNAPSHOT_KEY, raw)
        if raw:
            contract = json.loads(bess_config.canonical_json(raw))
        else:
            from domain.bess.synthetic import example
            from finco_core.engine.period_engine import PeriodEngine
            snapshot = ws.draft_snapshot or {}
            cod = date.fromisoformat(str(snapshot.get('cod_date') or '2031-01-01'))
            from dateutil.relativedelta import relativedelta
            months = int(snapshot.get('construction_months') or 12)
            horizon = int(snapshot.get('horizon_years') or 25)
            axis = tuple(p for p in PeriodEngine(cod - relativedelta(months=months), months, horizon, 0, cod_date=cod).periods() if p.is_operation)
            config = example(axis[0].start_date.isoformat() + 'T00:00:00Z', axis[-1].end_date.isoformat() + 'T00:00:00Z')
            config['battery']['useful_life_years'] = horizon
            contract = {'version': 1, 'configuration': config, 'variable_om_eur_per_dc_mwh': 0}
        identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        return templates.TemplateResponse(request=request, name='v2/partials/bess_workspace.html', context={
            'configuration': contract['configuration'], 'variable_om': contract['variable_om_eur_per_dc_mwh'],
            'native_contract': contract, 'project': record, 'readonly': is_protected_reference(record) or owner != user.user_id,
            'content_hash': identity.composite_hash, 'csrf_token': generate_csrf_token(), 'workbook_version': WORKBOOK.version,
            'is_initial_example': not raw, 'audit': (ws.last_runtime_summary or {}).get('bess_operating_audit', []),
        }, headers={'Cache-Control': 'no-store'})
    except PermissionError as exc:
        return JSONResponse({'error': str(exc)}, status_code=401)
    except LookupError as exc:
        return JSONResponse({'error': str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=409)


@router.post('/workbook/bess/save')
async def save(request: Request, _: None = Depends(require_v2_active)):
    if not bess_config.ACTIVATION_ENABLED:
        return JSONResponse({'error': 'BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED'}, status_code=404)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_REQUEST_BYTES:
            return JSONResponse({'error': 'BESS_REQUEST_TOO_LARGE'}, status_code=413)
    from urllib.parse import parse_qs
    try:
        if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            raise ValueError('BESS_FORM_ENCODING')
        form = parse_qs(bytes(data).decode('utf-8'), keep_blank_values=True, max_num_fields=5)
        if set(form) != {'project', 'content_hash', 'csrf_token', 'workbook_version', 'configuration'} or any(len(v) != 1 for v in form.values()):
            raise ValueError('BESS_FORM_SCHEMA')
        form = {k: v[0] for k, v in form.items()}
        user, record, owner = scope(request, form['project'])
        if not validate_csrf_token(form['csrf_token']):
            return JSONResponse({'error': 'BESS_CSRF_INVALID'}, status_code=403)
        if owner != user.user_id or is_protected_reference(record):
            return JSONResponse({'error': 'BESS_READ_ONLY'}, status_code=403)
        if form['workbook_version'] != WORKBOOK.version:
            raise ValueError('BESS_WORKBOOK_VERSION_MISMATCH')
        from app.workbook.revenue_contracts_service import save_contracts
        save_contracts(owner=owner, project_id=record.project_id, expected_hash=form['content_hash'],
                       raw=form['configuration'], field_id=bess_config.FIELD_ID)
        from urllib.parse import quote
        return RedirectResponse('/v2/workbook?project=' + quote(record.project_code), status_code=303)
    except PermissionError as exc:
        return JSONResponse({'error': str(exc)}, status_code=401)
    except LookupError as exc:
        return JSONResponse({'error': str(exc)}, status_code=404)
    except (ValueError, UnicodeDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=409)
