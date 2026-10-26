"""V11 P2a: ``run_history_repository._decode_entry`` decodes every stored JSON object column exactly once.

The previous decoder parsed each of the eight object columns twice (once to validate, once to build the entry).
The reference decoder below is a verbatim copy of that implementation; the tests prove the single-pass decoder
returns identical entries, raises identical first failures, keeps every fail-closed contract and parses fewer
documents. Everything here is synthetic and uses a disposable database.
"""
from __future__ import annotations

import datetime
import json
import threading
from types import SimpleNamespace

import pytest

from app.persistence import run_history_repository as rh
from app.persistence.db import get_cursor, init_db
from app.persistence import projects_repository
from app.persistence.run_history_repository import (
    RunHistoryEntry, RunHistoryError, append_run_history_cursor, get_latest_history_entry, get_run_history,
    get_run_history_entry, prepare_run_history_payload,
)
from app.persistence.workspace_repository import save_workspace_state

USER = "u-p2a"
OTHER_USER = "u-p2a-other"
CODE = "P2A-CODE"
OBJECT_COLUMNS = (
    "runtime_summary_json", "financial_statements_json", "debt_schedule_json", "tax_schedule_json",
    "distribution_schedule_json", "sponsor_schedule_json", "integrity_evidence_json", "replay_metadata_json",
)
BASE = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _legacy_decode_entry(row, loads=json.loads) -> RunHistoryEntry:
    """Verbatim copy of the pre-P2a decoder (every object column parsed twice)."""
    def _load(column: str):
        raw = row[column]
        try:
            return loads(raw)
        except (TypeError, ValueError) as exc:
            raise RunHistoryError(
                f"RUN_HISTORY_PAYLOAD_MALFORMED: column {column} is not "
                f"valid JSON ({exc})"
            ) from exc

    for column in rh._HISTORY_COLUMNS:
        if column not in row.keys():
            raise RunHistoryError(
                "RUN_HISTORY_PAYLOAD_MALFORMED: stored row is missing "
                f"column {column}"
            )
    identity_raw = row["last_runtime_identity_json"]
    identity_decoded = None
    if identity_raw is not None:
        try:
            identity_decoded = loads(identity_raw)
        except (TypeError, ValueError) as exc:
            raise RunHistoryError(
                "RUN_HISTORY_PAYLOAD_MALFORMED: last_runtime_identity_json "
                f"is not valid JSON ({exc})"
            ) from exc
        if not isinstance(identity_decoded, dict):
            raise RunHistoryError(
                "RUN_HISTORY_PAYLOAD_MALFORMED: last_runtime_identity_json "
                "is not a JSON object"
            )
    for column in OBJECT_COLUMNS:
        decoded = _load(column)
        if not isinstance(decoded, dict):
            raise RunHistoryError(
                "RUN_HISTORY_PAYLOAD_MALFORMED: column "
                f"{column} is not a JSON object"
            )
    entry = RunHistoryEntry(
        history_id=row["history_id"], user_id=row["user_id"], project_id=row["project_id"],
        project_code=row["project_code"], runtime_snapshot_id=row["runtime_snapshot_id"],
        runtime_origin=row["runtime_origin"], ran_at=row["ran_at"], engine_version=row["engine_version"],
        workbook_version=row["workbook_version"], active_scenario_id=row["active_scenario_id"],
        active_scenario_name=row["active_scenario_name"], last_runtime_scenario_id=row["last_runtime_scenario_id"],
        composite_hash=row["composite_hash"], last_runtime_identity=identity_decoded,
        runtime_summary=_load("runtime_summary_json"), financial_statements=_load("financial_statements_json"),
        debt_schedule=_load("debt_schedule_json"), tax_schedule=_load("tax_schedule_json"),
        distribution_schedule=_load("distribution_schedule_json"), sponsor_schedule=_load("sponsor_schedule_json"),
        integrity_evidence=_load("integrity_evidence_json"), replay_metadata=_load("replay_metadata_json"),
        created_at=row["created_at"],
    )
    for field in ("history_id", "user_id", "project_id", "project_code",
                  "runtime_snapshot_id", "ran_at", "created_at"):
        if not getattr(entry, field):
            raise RunHistoryError(f"RUN_HISTORY_PAYLOAD_MALFORMED: {field} is empty")
    if not isinstance(entry.runtime_summary, dict):
        raise RunHistoryError("RUN_HISTORY_PAYLOAD_MALFORMED: runtime_summary is not an object")
    return entry


class _CountingJson:
    """Delegates to the real ``json`` module, counting ``loads`` calls."""

    def __init__(self):
        self.loads_calls = 0

    def loads(self, *args, **kwargs):
        self.loads_calls += 1
        return json.loads(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(json, name)


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "p2a.db"))
    init_db()
    # Resolve through the module at call time: other suites reload projects_repository, which would leave a
    # module-level ``save_project`` bound to a stale ``_UNSET`` sentinel default.
    snapshot = {"active_project": CODE, "capacity_mw": "64"}
    record = projects_repository.save_project(user_id=USER, project_code=CODE, project_name="P2a",
                          source_project_template="generic_solar_reference")
    save_workspace_state(user_id=USER, project_id=record.project_id, project_code=CODE,
                         draft_snapshot=snapshot, saved_snapshot=snapshot)
    other = projects_repository.save_project(user_id=OTHER_USER, project_code="P2A-OTHER", project_name="Other",
                         source_project_template="generic_solar_reference")
    save_workspace_state(user_id=OTHER_USER, project_id=other.project_id, project_code="P2A-OTHER",
                         draft_snapshot=snapshot, saved_snapshot=snapshot)
    return SimpleNamespace(project_id=record.project_id, other=other)


def _append(project_id, index, *, user_id=USER, code=CODE, blob_chars=0, identity=True, ran_at=None):
    filler = {"filler": "x" * blob_chars} if blob_chars else {}
    payload = prepare_run_history_payload(
        user_id=user_id, project_id=project_id, project_code=code, runtime_snapshot_id=f"snap-{index:04d}",
        runtime_origin="v2_run", ran_at=(ran_at or (BASE + datetime.timedelta(minutes=index))).isoformat(),
        runtime_summary={"n": index, **filler}, financial_statements={"fs": [index, 1.5], **filler},
        debt_schedule={"d": index}, tax_schedule={"t": index}, distribution_schedule={"x": index},
        sponsor_schedule={"s": index}, engine_version="e1", workbook_version="w1", composite_hash=f"h{index}",
        last_runtime_identity={"composite_hash": f"h{index}", "k": index} if identity else None,
        integrity_evidence={"i": index}, replay_metadata={"r": index},
    )
    with get_cursor() as cur:
        return append_run_history_cursor(cur, payload)


def _rows(project_id, user_id=USER):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM model_run_history WHERE user_id=? AND project_id=? "
                    "ORDER BY ran_at DESC, history_id DESC", (user_id, project_id))
        return cur.fetchall()


def _update(history_id, **columns):
    with get_cursor() as cur:
        cur.execute("UPDATE model_run_history SET " + ", ".join(f"{c}=?" for c in columns) + " WHERE history_id=?",
                    (*columns.values(), history_id))


def _outcome(decoder, row):
    try:
        return ("ok", decoder(row).to_dict())
    except RunHistoryError as exc:
        return ("err", str(exc))


# ---------------------------------------------------------------------------------------------- equivalence

@pytest.mark.parametrize("count", (0, 1, 10, 25, 55))
def test_new_decoder_returns_identical_entries_for_every_history_size(workspace, count):
    for i in range(count):
        _append(workspace.project_id, i, identity=bool(i % 2), blob_chars=50 * (i % 5))
    rows = _rows(workspace.project_id)
    assert len(rows) == count
    assert [r["history_id"] for r in rows] == [e.history_id for e in get_run_history(USER, workspace.project_id)]
    for row in rows:
        assert rh._decode_entry(row).to_dict() == _legacy_decode_entry(row).to_dict()
        assert rh._decode_entry(row) == _legacy_decode_entry(row)


def test_large_payloads_decode_identically(workspace):
    for i in range(5):
        _append(workspace.project_id, i, blob_chars=300_000)
    for row in _rows(workspace.project_id):
        assert rh._decode_entry(row) == _legacy_decode_entry(row)


def test_legacy_and_v2_bound_identity_round_trip(workspace):
    legacy = _append(workspace.project_id, 1, identity=False)
    bound = _append(workspace.project_id, 2)
    binding = {"working_copy_ref": CODE, "snapshot_id": "snap-0002", "economic_identity": "e" * 64}
    _update(bound, last_runtime_identity_json=json.dumps({"composite_hash": "h2", "model_v2": binding}))
    assert get_run_history_entry(USER, workspace.project_id, legacy).model_v2_binding is None
    entry = get_run_history_entry(USER, workspace.project_id, bound)
    assert entry.model_v2_binding == binding
    assert entry.last_runtime_identity == {"composite_hash": "h2", "model_v2": binding}
    for row in _rows(workspace.project_id):
        assert rh._decode_entry(row) == _legacy_decode_entry(row)


def test_newest_first_with_history_id_tiebreak_and_scoping(workspace):
    same = BASE + datetime.timedelta(hours=1)
    ids = [_append(workspace.project_id, i, ran_at=same) for i in range(4)]
    older = _append(workspace.project_id, 9, ran_at=BASE)
    _append(workspace.other.project_id, 1, user_id=OTHER_USER, code="P2A-OTHER")
    listed = [e.history_id for e in get_run_history(USER, workspace.project_id)]
    assert listed == sorted(ids, reverse=True) + [older]
    assert get_latest_history_entry(USER, workspace.project_id).history_id == listed[0]
    assert [e.user_id for e in get_run_history(OTHER_USER, workspace.other.project_id)] == [OTHER_USER]
    assert get_run_history_entry(USER, workspace.other.project_id, listed[0]) is None
    assert get_run_history_entry(OTHER_USER, workspace.project_id, listed[0]) is None


# ---------------------------------------------------------------------------------------------- the P2a claim

def test_each_object_column_is_parsed_exactly_once(workspace, monkeypatch):
    _append(workspace.project_id, 1)
    row = _rows(workspace.project_id)[0]
    counter = _CountingJson()
    monkeypatch.setattr(rh, "json", counter)
    rh._decode_entry(row)
    assert counter.loads_calls == len(OBJECT_COLUMNS) + 1          # 8 object columns + the separate identity document
    legacy_counter = _CountingJson()
    _legacy_decode_entry(row, loads=legacy_counter.loads)
    assert legacy_counter.loads_calls == 2 * len(OBJECT_COLUMNS) + 1       # the pre-P2a decoder: 17 parses


def test_null_identity_costs_only_the_eight_object_parses(workspace, monkeypatch):
    _append(workspace.project_id, 1, identity=False)
    row = _rows(workspace.project_id)[0]
    counter = _CountingJson()
    monkeypatch.setattr(rh, "json", counter)
    assert rh._decode_entry(row).last_runtime_identity is None
    assert counter.loads_calls == len(OBJECT_COLUMNS)


def test_listing_parses_linearly_in_history_size(workspace, monkeypatch):
    for i in range(25):
        _append(workspace.project_id, i)
    counter = _CountingJson()
    monkeypatch.setattr(rh, "json", counter)
    assert len(get_run_history(USER, workspace.project_id)) == 25
    assert counter.loads_calls == 25 * (len(OBJECT_COLUMNS) + 1)       # previously 25 * 17
    counter.loads_calls = 0
    assert get_latest_history_entry(USER, workspace.project_id) is not None
    assert counter.loads_calls == len(OBJECT_COLUMNS) + 1


# ---------------------------------------------------------------------------------------------- fail closed

_BAD_VALUES = ("{not json", "[1, 2]", '"text"', "7", "true", "null", "")


@pytest.mark.parametrize("column", OBJECT_COLUMNS)
@pytest.mark.parametrize("bad", _BAD_VALUES)
def test_every_object_column_fails_closed_with_the_same_message(workspace, column, bad):
    history_id = _append(workspace.project_id, 1)
    _append(workspace.project_id, 2)
    _update(history_id, **{column: bad})
    row = next(r for r in _rows(workspace.project_id) if r["history_id"] == history_id)
    new, old = _outcome(rh._decode_entry, row), _outcome(_legacy_decode_entry, row)
    assert new[0] == "err" and new == old
    assert "RUN_HISTORY_PAYLOAD_MALFORMED" in new[1] and column in new[1]
    for call in (lambda: get_run_history(USER, workspace.project_id),
                 lambda: get_run_history_entry(USER, workspace.project_id, history_id)):
        with pytest.raises(RunHistoryError, match="RUN_HISTORY_PAYLOAD_MALFORMED"):
            call()


@pytest.mark.parametrize("column", OBJECT_COLUMNS)
def test_null_object_column_from_a_foreign_row_fails_closed(workspace, column):
    _append(workspace.project_id, 1)
    row = _rows(workspace.project_id)[0]
    foreign = {key: row[key] for key in row.keys()}              # the schema forbids NULL; a mapping can carry it
    foreign[column] = None
    new, old = _outcome(rh._decode_entry, foreign), _outcome(_legacy_decode_entry, foreign)
    assert new[0] == "err" and new == old and column in new[1]


def test_first_failure_is_the_same_when_several_columns_are_corrupt(workspace):
    history_id = _append(workspace.project_id, 1)
    _update(history_id, tax_schedule_json="[]", debt_schedule_json="{bad", sponsor_schedule_json="1",
            last_runtime_identity_json=None)
    row = _rows(workspace.project_id)[0]
    assert _outcome(rh._decode_entry, row) == _outcome(_legacy_decode_entry, row)
    assert "debt_schedule_json" in _outcome(rh._decode_entry, row)[1]          # declared order: debt before tax
    _update(history_id, last_runtime_identity_json="[broken")
    row = _rows(workspace.project_id)[0]
    new = _outcome(rh._decode_entry, row)
    assert new == _outcome(_legacy_decode_entry, row) and "last_runtime_identity_json" in new[1]


@pytest.mark.parametrize("bad", ("[broken", "[]", '"s"', "5", "true", "{x"))
def test_invalid_identity_document_fails_closed(workspace, bad):
    history_id = _append(workspace.project_id, 1)
    _update(history_id, last_runtime_identity_json=bad)
    with pytest.raises(RunHistoryError, match="RUN_HISTORY_PAYLOAD_MALFORMED"):
        get_run_history(USER, workspace.project_id)
    row = _rows(workspace.project_id)[0]
    assert _outcome(rh._decode_entry, row) == _outcome(_legacy_decode_entry, row)


def test_missing_required_column_fails_closed(workspace):
    _append(workspace.project_id, 1)
    with get_cursor() as cur:
        cur.execute("SELECT history_id, user_id FROM model_run_history")
        partial = cur.fetchone()
    for decoder in (rh._decode_entry, _legacy_decode_entry):
        with pytest.raises(RunHistoryError, match="RUN_HISTORY_PAYLOAD_MALFORMED: stored row is missing column"):
            decoder(partial)
    assert _outcome(rh._decode_entry, partial) == _outcome(_legacy_decode_entry, partial)


@pytest.mark.parametrize("field", ("project_code", "runtime_snapshot_id", "ran_at", "created_at"))
def test_empty_required_text_fields_fail_closed(workspace, field):
    history_id = _append(workspace.project_id, 1)
    _update(history_id, **{field: ""})
    row = _rows(workspace.project_id)[0]
    new = _outcome(rh._decode_entry, row)
    assert new[0] == "err" and f"{field} is empty" in new[1]
    assert new == _outcome(_legacy_decode_entry, row)


# ---------------------------------------------------------------------------------------------- read-only, concurrency

def test_listing_never_writes(workspace):
    for i in range(12):
        _append(workspace.project_id, i, blob_chars=1000)
    before = [tuple(r) for r in _rows(workspace.project_id)]
    for _ in range(3):
        get_run_history(USER, workspace.project_id)
        get_latest_history_entry(USER, workspace.project_id)
        get_run_history_entry(USER, workspace.project_id, before[0][0])
    assert [tuple(r) for r in _rows(workspace.project_id)] == before
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM model_run_history")
        assert cur.fetchone()[0] == 12


def test_concurrent_append_during_listing_stays_consistent(workspace):
    for i in range(10):
        _append(workspace.project_id, i)
    errors: list = []
    stop = threading.Event()

    def writer():
        try:
            for i in range(10, 30):
                _append(workspace.project_id, i)
        except Exception as exc:        # noqa: BLE001
            errors.append(exc)
        finally:
            stop.set()

    thread = threading.Thread(target=writer)
    thread.start()
    sizes = []
    while not stop.is_set() or len(sizes) < 3:
        listing = get_run_history(USER, workspace.project_id)
        keys = [(e.ran_at, e.history_id) for e in listing]
        assert keys == sorted(keys, reverse=True)
        sizes.append(len(listing))
        if len(sizes) > 400:
            break
    thread.join()
    assert not errors
    assert sizes == sorted(sizes) and sizes[-1] >= 10
    assert len(get_run_history(USER, workspace.project_id)) == 30
