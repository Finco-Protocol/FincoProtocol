"""Rebuild the React bundle and refresh the RC_UX_SUCCESSORS layer from the committed sources (run from the repo root).
The layer holds EVERY pinned path whose current blob is not an earlier admitted state (original / earlier layers / RC-M)."""
import hashlib, json, re, shutil, subprocess, sys
import os; ROOT = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip() + "/"
def blob(path):
    raw = open(ROOT + path, "rb").read()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
if "--no-build" not in sys.argv:
    subprocess.check_call(["npm", "run", "build"], cwd=ROOT + "frontend", stdout=subprocess.DEVNULL)
    for name in ("finco-react.js", "finco-react.css"):
        shutil.copyfile(ROOT + "frontend/dist/" + name, ROOT + "static/react/" + name)
sys.path.insert(0, ROOT)
from tests import model_mutation_security_successor as S  # noqa
MAIN = "70bcf693bdb2547fc1c0e5af685835689eb44d3e"   # main = FIN-V2 Integration RC (PR #395)
def main_blob(path):
    try:
        return subprocess.check_output(["git", "rev-parse", MAIN + ":" + path], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return None
layer = {}
for p in sorted(S.BLOBS):
    b = blob(p)
    if b == main_blob(p):          # unchanged by RC-UX: admitted by the reviewed FIN-V2 cohort composite (tests/fin_v2_cohorts.py), never re-pinned here
        continue
    bl = S._browser_layers().get(p)
    earlier = {bl[2] if bl else None, S.BLOBS[p], S.FINVAL_B2C1_SUCCESSORS.get(p), S.D029_RUN_INTENT_SUCCESSORS.get(p), S.REACT_MVP_CORRECTION_SUCCESSORS.get(p),
               S.FINVAL_RATE_SUCCESSORS.get(p), S.FINVAL_F01_COMPLETE_SUCCESSORS.get(p), S.RC_M_SUCCESSORS.get(p)} - {None}
    if b not in earlier:
        layer[p] = b
body = "RC_UX_SUCCESSORS={\n" + "".join(f'    "{p}":"{b}",\n' for p, b in layer.items()) + "}\n"
f = ROOT + "tests/model_mutation_security_successor.py"
s = open(f).read()
s = re.sub(r"RC_UX_SUCCESSORS=\{\n(?:    .*\n)*?\}\n", body, s, count=1)
open(f, "w").write(s)
print(sorted(layer))

# ── cohort manifests ───────────────────────────────────────────────────────────────────────────────────────────────────────────
# RC-UX owns (a) its own cohort manifest and (b) re-pins ONLY these governance test files inside the other FIN-V2 cohort manifests, because
# the successor layer / RC-UX successor logic lives there.  Every other pin (engine, persistence, workbook, ...) is never touched here.
REPIN = {"tests/model_mutation_security_successor.py", "tests/test_model_mutation_security_successor.py",
         "tests/test_model_react_overnight_b_governance.py", "tests/test_rcm_governance.py",
         "tests/model_react_mvp_acceptance.py", "tests/model_react_overnight_b_acceptance.py", "tests/fin_v2_cohorts.py",
         "tests/test_finv2_d01_routes_and_matrix.py"}
OTHER = ["docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json", "docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json",
         "docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json", "docs/financial_validation/fin_v2_ci/SOURCE_SUCCESSOR.json"]
def dump(path, data):
    open(ROOT + path, "w").write(json.dumps(data, indent=2) + "\n")
for m in OTHER:
    d = json.load(open(ROOT + m))
    for p in d["source_blobs"]:
        if p in REPIN:
            d["source_blobs"][p] = blob(p)
    dump(m, d)
from tests import fin_v2_rcux_scope as R  # noqa
dump(R.MANIFEST, {"schema_version": R.SCHEMA, "base": R.BASE,
     "authorization": "Financial Owner assigned RC-UX Completion V1 (incl. Addenda A and B): in-scope React presentation, read-only adapters, governance successors; "
                      "no merge, deployment, feature activation or financial-engine change. Self-generated exact blobs: a review proposal, not an approval.",
     "source_blobs": {p: blob(p) for p in sorted(R.OWNED_PATHS)}})
print("cohort manifests refreshed")
