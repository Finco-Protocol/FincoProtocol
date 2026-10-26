"""Model mutation request tokens: session, project and operation bound.

Project access, protected-reference checks and transactional CAS remain separate
authorities. Existing Run/Clone/Capital Stack token domains are unchanged.
"""
from app import auth
from app.workbook.financing_csrf import extract_bound_token, issue_token

OPERATIONS = frozenset({
    "scenario-create", "scenario-select", "scenario-rename", "scenario-archive",
    "scenario-update-overrides", "scenario-remove-override", "workbook-update",
    "reference-seed-reset", "workbook-export", "grid-save", "grid-cost-lines-save",
    "capex-add", "capex-update", "capex-deactivate", "capex-reactivate", "capex-reorder", "capex-contingency",
    "opex-add", "opex-update", "opex-deactivate", "opex-reactivate", "opex-reorder",
})


def mutation_token(request, project: str, operation: str) -> str:
    if operation not in OPERATIONS:
        raise ValueError("Unknown model mutation operation")
    return issue_token(request, project, purpose="model-mutation-v1:" + operation)


def mutation_tokens(request, project: str) -> dict[str, str]:
    return {operation: mutation_token(request, project, operation) for operation in sorted(OPERATIONS)}


def validate_mutation_token(request, project: str, supplied, operation: str) -> bool:
    if operation not in OPERATIONS:
        return False
    return auth.validate_csrf_token(extract_bound_token(
        request, project, supplied, purpose="model-mutation-v1:" + operation))
