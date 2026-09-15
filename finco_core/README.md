# finco_core

**FINCO Protocol v2 — Financial Engine Core Package**

`finco_core` is the extraction target for the validated FINCO Protocol financial engine. It will become a standalone Python package containing all mathematical engine code, typed input and output models, and supporting financial calculations. It has zero dependencies on web frameworks, UI frameworks, or persistence libraries.

## Package Responsibilities

| Subpackage | Responsibility |
|------------|---------------|
| `inputs/` | Typed input models: ProjectInputs, FinancingParams, ProjectInfo, RunConfiguration |
| `engine/` | Top-level orchestration: FinancialEngine → EngineResult |
| `waterfall/` | Innermost cashflow engine: WaterfallPeriod, WaterfallResult, run_waterfall |
| `tax/` | TaxEngine, LossCarryforward (Generic Market An CIT §16, 5-year rolling) |
| `debt/` | Senior debt schedule, DSCR sculpting, covenant engine |
| `depreciation/` | Book and tax depreciation ledger |
| `shl/` | Shareholder loan engine, canonical wiring, repayment alignment |
| `sponsor/` | Sponsor cashflow, multi-investor waterfall, equity IRR |
| `audit/` | Typed AuditResult contract (read-only view of EngineResult) |
| `exports/` | Typed ExportResult contract (serialisable output) |
| `validation/` | Input boundary validation |

## Dependency Rule

`finco_core` depends on **nothing** outside the Python standard library.

`finco_app` depends on `finco_core`.  
`finco_parity` depends on `finco_core`.  
`finco_core` never imports from `finco_app`, `finco_parity`, or any UI package.

## Extraction Status

| Milestone | Status |
|-----------|--------|
| V2-1 Skeleton | In progress |
| V2-2 Inputs | Planned |
| V2-3 Engine | Planned |
| V2-4 Parity gate | Planned |

## Parity Baseline

All engine extraction must be validated against the `FINCO Protocol-RC2` baseline (SHA: `b52d39c`).  
See `docs/RC2_BASELINE.md` for tolerance targets.
