# Lane A — CAPEX spending-profile studio (Audit A GAP-R9)

| Piece | Path | Notes |
|---|---|---|
| Read adapter | `app/v2/react_capex.py` (mounted by `react_rcux.py`) | `GET /v2/model-react/capex/profiles` (items, timeline, saved profile, binding, committed Last Run S&U, save contract) and `GET /v2/model-react/capex/preview` (ephemeral allocation of a draft; header-guarded; bounded `spec`). Reuses `app.v2.capex_profile_router` helpers and `app.capex_profiles.plan.build_plan`; no allocation/rounding/IDC code is added. |
| Write | existing `POST /v2/capex/spending-profiles/save` | CSRF + composite-hash CAS + exclusive transaction, unchanged. The React editor posts the canonical form, then re-reads to verify; an unverifiable outcome locks the studio (never retried). |
| UI | `frontend/src/app/capex/CapexStudio.tsx`, hub `studios/InputStudios.tsx` (Inputs > Studios) | Shapes UNIFORM / FRONT / BACK / EXPLICIT / MILESTONE; Excel/CSV paste into the explicit weights; bulk shape, undo, discard, remove (dialog); exact per-month table with cumulative/remaining, period equivalents, CSV/TSV copy; committed Last Run Sources & Uses clearly separated from the draft. |

**IDC / Sources & Uses:** not estimated pre-Run (stated in the UI). Their impact is visible only in the committed Run: the acceptance test proves a React-saved FRONT_LOADED profile yields the same IDC, Total Uses and IRR as a Legacy-service-saved twin, and that Save marks the Last Run STALE without running.

**Deferred:** file upload of profiles (Excel/CSV *file*) belongs to the Import workspace (GAP-R10); only clipboard paste is supported here.
