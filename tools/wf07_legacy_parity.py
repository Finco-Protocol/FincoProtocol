"""Read-only comparison runner; compare complete financial trees, not target-fitting KPIs."""
import argparse
import dataclasses
import enum
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
import sys


def exact(value):
    if isinstance(value, float):
        return {"float_hex": value.hex()}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return {f.name: exact(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): exact(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [exact(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--compare")
    args = parser.parse_args()
    sys.path.insert(0, args.repo)
    from app import project_factories as factories
    from app.services.production_financial_authority import run_clean_production
    results = {}
    for kind in ("solar", "wind", "data_center", "ev_charging"):
        pi = getattr(factories, "create_generic_" + kind + "_reference")()
        run = run_clean_production(pi, "Base", project_type=kind)
        tree = exact(run)
        results[kind] = {"sha256": hashlib.sha256(json.dumps(tree, sort_keys=True).encode()).hexdigest(), "tree": tree}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, sort_keys=True, indent=2), encoding="utf-8")
    if args.compare:
        baseline = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        for kind in results:
            if results[kind] != baseline[kind]:
                raise AssertionError(f"Inactive financial tree differs: {kind}")
    print(json.dumps({kind: result["sha256"] for kind, result in results.items()}, indent=2))
    if args.compare:
        print("FOUR_VERTICAL_COMPLETE_FINANCIAL_TREE_BIT_EXACT")


if __name__ == "__main__":
    main()
