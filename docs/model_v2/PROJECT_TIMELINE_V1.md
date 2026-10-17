# Project Timeline V1 (WF-10)

Read-only presentation inside Project Setup. It creates no date authority, writes nothing and never runs the model.

## Authority and chronology

| Shown | Source | Rule |
|---|---|---|
| COD | saved `project_setup.technical.cod_date` | displayed as persisted ("saved input") |
| Duration | saved `project_setup.technical.construction_months` | whole months |
| Construction start | derived, tagged "derived: COD − duration" | `FincoDates.addMonths(COD, −months)`, the same calendar convention as the Construction Timing editor and the period engine (`relativedelta` months, month-end clamped, leap years); never 30-day months or 365-day years |
| Horizon | saved `project_setup.technical.horizon_years` | whole years |
| Modeled end date | **not derived** | the exact operating end comes from the period calendar at Run; the timeline says so instead of inventing an endpoint |

## Checks (warnings only, nothing repaired, nothing blocked)

Missing or invalid COD, missing/invalid duration, derived start not before COD, a COD that cannot be reproduced as start + duration under the month-end convention, invalid horizon. Server-side model validation stays authoritative.

## Milestones not recorded

Financial Close, Notice to Proceed, debt drawdown dates, refinancing date, financing maturity, decommissioning: listed as not recorded; never given dates.

## Construction Timing relationship

The timeline reads saved values (server-rendered `data-*`). On an accepted Save the editor's `ct:saved` event refreshes it with the accepted values, and the editor's existing HTMX replacement re-renders it from the saved inputs. An unsaved or rejected draft is only flagged ("not reflected in this timeline"). No second Save, no fetch, no Run, no Run-state change.

## Files

`app/templates/v2/partials/sheet_project_setup.html` (section only), `static/js/model_project_timeline.js`, `static/css/model_project_timeline.css`, `tests/test_model_project_timeline_v1.py`, `tests/test_model_project_timeline_browser.py`.

## Limitations

The exact modeled end date is not shown. Calendar math is mirrored from `FincoDates` (display only) and verified against `dateutil.relativedelta` in Chromium.
