import sys,json,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import pytest
from tests.test_fin_val_b2_c1_recovery_finite_opex import env,_prime,_snapshot,USER
from app.workbook.input_set import ProjectInputSet
from app.input_adapter import senior_rate_authority
mp=pytest.MonkeyPatch()
gen=env.__wrapped__(Path(tempfile.mkdtemp(prefix='f01-baseline-')),mp);e=next(gen)
try:
 rec=e.create('solar');_prime(e,rec)
 def observe():
  api=e.client.get('/v2/model-react/fields/debt',params={'project':rec.project_code}).json()
  field=next(f for f in api['fields'] if f['field_id']=='debt.senior.interest_rate_pct')
  snap=_snapshot(rec);pi=ProjectInputSet.from_snapshot(snap).to_projectinputs()
  return {'raw':snap['interest_rate_pct'],'display':field['display_value'],'typed_ratio':senior_rate_authority(pi)[1]},api['save']
 before,token=observe()
 response=e.client.post('/v2/workbook/update',headers={'HX-Request':'true'},data={'project':rec.project_code,'field_id':'debt.senior.interest_rate_pct','value':'.056',**token})
 assert response.status_code==200,response.text[:200]
 after,_=observe()
 result={'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'before':before,'posted_human_pct':.056,'after':after}
 Path('/workspace/artifacts/finval-f01-complete/live-main-reproduction.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
finally:
 try:next(gen)
 except StopIteration:pass
 mp.undo()
