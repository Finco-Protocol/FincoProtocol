"""Rebuild the React bundle and refresh the RC_UX_SUCCESSORS layer from the committed sources (run from the repo root).
The layer holds EVERY pinned path whose current blob is not an earlier admitted state (original / earlier layers / RC-M)."""
import hashlib, re, shutil, subprocess, sys
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
layer = {}
for p in sorted(S.BLOBS):
    b = blob(p)
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
