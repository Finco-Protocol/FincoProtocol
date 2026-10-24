# Source-aware mandatory execution (main-only successor)

The fixed `e96561a...` application/dependency comparison originally restricted
historical outcome reuse to a CI-only successor. It existed twice: in routing
and in `authenticate_baseline`. Removing only routing would select workers whose
planner still rejected the application source. Historical coverage also predates
later accepted tests, so comparing only that inventory could miss their deletion.

The successor preserves the original control's pinned service artifacts and
re-executes its original verifier in its original checkout. It never calls that
control a current-source sequential execution. The additional regression
reference is the GitHub-event-pinned accepted base: PR base SHA, or push `before`.
Its successful ordinary Public Safety run must contain successful source safety,
stable tests and mandatory evidence. An ancestor is eligible only with an
identical Git tree; its actual run/attempt and artifact digests remain distinct.
Its own original verifier checks the downloaded artifacts in the reviewed
reference source checkout. No tests are rerun to recover that reference.

Routing authenticates this reference before selecting parallel; unavailable or
incompatible admission selects sequential. The planner repeats authentication,
collects the full current source, records all added IDs, and assigns whole-module
LPT ownership using the existing groups and configured worker count (default 5,
range 2–12). Every existing reference node and historical-control node must remain.
Collection skips must reconcile exactly. The aggregate proves current-source
coverage, native JUnit, complete phases, cleanup, calibration, environment and
image identity. Common outcomes must match both references; new nodes must pass.
The independent aggregate and mandatory gate reauthenticate the accepted-source
reference, rather than trusting a producer's snapshot. Snapshots are flat; they
never accumulate recursive evidence archives.

The reference does not authorize changed financial assertions or expected
outcomes. Existing financial/source-governance workflows and browser acceptance
remain mandatory. Removed/renamed nodes, changed collection skips, new nonpass or
changed expected phases are deliberately unsupported without separately reviewed
reconciliation authority; they remain blocking, not implicit approvals.

Dependency changes require coherent reviewed changes to the runtime inputs
contract, complete Python lock and image build inputs. Routing rejects mismatched
input hashes before parallel selection; planning and verification require the
actual complete installed package set to match the lock. The runtime is still
built once and transferred immutably to workers. No registry digest is fabricated.

The event source base and PR synthetic merge identity are bound throughout the
reusable workflow, plan, workers and both independent verification stages.
Selected parallel failures remain red. `CI_V3_MANDATORY_ROLLBACK=true` selects the
retained sequential execution on subsequent runs.

This change targets main only. PR #357 overlaps `tests/test_ci_v3_production.py`
and `app/persistence/db.py`. No Epic branch or UX feature branch is changed.
A later Epic integration requires separate review after the main correction is
approved and normally merged. The application edit here only clarifies the
already merged SQLite lifecycle docstring; no application behavior changes.
