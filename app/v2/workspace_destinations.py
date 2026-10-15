"""One presentation-only destination manifest; tab IDs remain compatibility contracts."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    tab_id: str
    label: str
    area: str
    default: bool = False
    alias_of: str = ""


DESTINATIONS = (
    Destination("tab-overview", "Overview", "overview", True),
    Destination("tab-diagnostics", "Model Diagnostics", "diagnostics", True),
    Destination("tab-input-grid", "Assumptions grid", "inputs", True),
    Destination("tab-project-setup", "Project setup", "inputs"),
    Destination("tab-inputs", "Inputs summary", "inputs"),
    Destination("tab-revenue", "Revenue", "inputs"),
    Destination("tab-capex", "CAPEX", "inputs"),
    Destination("tab-opex", "OPEX", "inputs"),
    Destination("tab-debt", "Senior debt", "financing", True),
    Destination("tab-investor", "Investors", "financing"),
    Destination("tab-tax", "Tax assumptions", "inputs"),
    Destination("tab-scenarios", "Selection & overrides", "scenarios", True),
    Destination("tab-outputs", "Financial results", "outputs", True),
    Destination("tab-fs", "Financial Statements (compatibility)", "outputs", alias_of="tab-outputs"),
    Destination("tab-returns", "Returns", "outputs"),
    Destination("tab-run-history", "Run History", "outputs"),
    Destination("tab-sensitivity", "Sensitivity", "analysis", True),
    Destination("tab-goal-seek", "Goal Seek / Tender Pricing", "analysis"),
    Destination("tab-compare", "Compare committed runs", "analysis"),
    Destination("tab-trust", "Trust · identity, assumptions & available lineage", "trust", True),
)

AREAS = (("inputs", "Inputs"), ("financing", "Financing"), ("outputs", "Results"), ("scenarios", "Scenarios"),
         ("analysis", "Analysis"), ("diagnostics", "Model Checks"), ("trust", "Trust"))


def navigation_manifest():
    """JSON-safe metadata, never input/run/evidence authority."""
    from dataclasses import asdict
    return {"areas": [{"id": key, "label": label} for key, label in AREAS],
            "destinations": [asdict(d) for d in DESTINATIONS]}
