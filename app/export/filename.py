"""Safe, human-readable download names; never financial identity authority."""
import re
import unicodedata


def model_results_filename(project_name, scenario_name, snapshot_id):
    def part(value, fallback):
        if str(value or "").strip().lower() in {"", "not_applicable", "unavailable", "not_available"}:
            return fallback
        ascii_text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
        return re.sub(r"[^A-Za-z0-9_-]+", "-", ascii_text).strip("-_")[:70] or fallback

    return "finco-{}-{}-results-{}.xlsx".format(
        part(project_name, "project"), part(scenario_name, "scenario-unrecorded"),
        part(snapshot_id, "run-unrecorded")[:16])
