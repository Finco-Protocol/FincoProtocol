# D13 — profile lifecycle: proof of the CURRENT behaviour (read-only)

Status: `CONTRACT_BLOCKED_OWNER_Q1`. Nothing in U2 changes Run semantics, the profile document or the binding.

| # | Behaviour today | Evidence (real app, synthetic projects) |
|---|---|---|
| L1 | Retiring a profiled CAPEX line keeps the profile document byte for byte | `test_u2_d13_profile_lifecycle.py::test_retire_keeps_the_document_and_the_run_is_refused_without_history` |
| L2 | The next Run is refused with `CAPEX_PROFILE_LEAF_UNKNOWN`; no history row is written; the last signed Run entry is unchanged | same test; protected `test_model_rc7_capex_profile_run.py::test_a_profile_orphaned_by_removing_its_leaf_fails_the_run_closed` |
| L3 | Reactivating the line restores a runnable state; the kept profile is used; one new history row | `::test_reactivate_restores_and_the_run_uses_the_kept_profile` |
| L4 | A stale composite hash on deactivate is refused; line and document unchanged | `::test_stale_hash_on_deactivate_changes_nothing` |
| L5 | Saving a document that still names the retired leaf is refused (binding); nothing written | `::test_saving_a_document_that_names_the_retired_leaf_is_refused` |
| L6 | The Studio sends only current items, so a Save while a line is retired would DROP its profile | U2 UI: banner `data-capex-orphans` + confirmation dialog "Remove the saved profile of retired lines?" (non-semantic; the user decides) |

UI disclosure added by U2:
* CAPEX · Lines row menu: a note before retiring a line that has a saved profile.
* Monthly schedule: a banner that names retired lines whose profile is still saved, and explains that the Run is refused until the line is reactivated
  or the profile is removed.
* A confirmation before Save removes them.
