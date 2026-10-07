import sys

sys.path.insert(0, ".")
from app import project_factories as F
import app.api.project_runner as runner
from app.services import production_financial_authority as pfa

pi = F.create_default_solar_project(capacity_mw=64.0)
runner.run_project("solar", "Base", project_inputs_override=pi)
pfa._POLICY_RUN_CACHE.clear()
runner.run_project("solar", "Base", project_inputs_override=pi)
print("warm run done")
