"""Versioned browser projection; canonical findings remain untouched on the server."""
from app.services.model_performance import observed

CLIENT_SCHEMA = "diagnostics_client_v1"


def diagnostics_client_payload(diagnostics):
    identity = diagnostics.get("identity") or {}
    checks = []
    for check in diagnostics.get("checks", []):
        periods = []
        for period in check.get("periods", []):
            compact = dict(period)
            inherited = {"check_id": check.get("check_id"), "snapshot_id": identity.get("snapshot_id"),
                         "run_identity": identity, "evidence_source": check.get("evidence_source")}
            for key, value in inherited.items():
                if key in compact and compact[key] == value:
                    del compact[key]
            periods.append(compact)
        checks.append({**check, "periods": periods})
    # groups/top_issues duplicate checks; waterfall and inventory are already HTML.
    # Retain bankability/history metadata used by the existing acceptance contract.
    payload = {key: value for key, value in diagnostics.items()
               if key not in {"groups", "top_issues", "waterfall", "v2", "checks"}}
    payload.update({"client_schema": CLIENT_SCHEMA, "checks": checks})
    if diagnostics.get("v2") is not None:
        v2 = diagnostics["v2"]
        payload["v2"] = {key: value for key, value in v2.items() if key != "inventory"}
    return payload


@observed("json_serialization")
def diagnostics_client_json(diagnostics):
    from jinja2.utils import htmlsafe_json_dumps
    return htmlsafe_json_dumps(diagnostics_client_payload(diagnostics), sort_keys=True)
