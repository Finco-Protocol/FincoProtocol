# PR-U2 financial parity ledger

U2 changes no financial formula, engine, binding, schema, Save All or Run path. Every number U2 shows is read from an existing authority.

| Surface | Number | Authority | Changed? | Parity evidence |
|---|---|---|---|---|
| OPEX · Years per line | line value in year t | `OpexLineVM.year_values` (same view model as the group projection and the Legacy sheet) | no (pass-through) | independent oracle `y1 × (1+i)^(t−1)` from the saved ledger, rel 1e-12, 4 verticals (`test_u2_opex_lines.py`) |
| OPEX · Years group / totals | group row, contingency, totals | `/v2/model-react/opex-projection` | no | exact equality (`==`) of every value |
| OPEX · Years bases | six base scalars, Year 1 | `cost_line_ledger.opex_bases` | no | equality with the costlines projection bases |
| CAPEX · Monthly check | accept / refuse an EXPLICIT row | `contract.build_weights` (server) | no (client mirror only) | client == server on 18 synthetic cases incl. both tolerance edges (`test_u2_profile_import.py`) |
| CAPEX profile → Run | funding schedule / IDC | engine + binding | no | protected RC-7 suite unchanged; D13 proofs read-only |
| Save All / profile save | persisted inputs | existing writers | no | T1–T3 two-writer oracle |

Financial truth that changed: **none**. Unchanged: every signed Run, the Run history, the Last Run view, the profile document format, the six base
scalars' Run treatment, and the end-of-period default (D6).
