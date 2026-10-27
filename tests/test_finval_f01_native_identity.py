"""F01 edited-rate exact identity on approved native kernels; no kernel changes."""
from dataclasses import replace
import json,os
from pathlib import Path
import pytest
from app import project_factories as pf
from app.input_adapter import _resolve_user_inputs, senior_rate_authority
from tests.native_v11_support import run_case, outcome_key

pytestmark=pytest.mark.usefixtures('stage3_artifacts')

@pytest.mark.parametrize('kind',['solar','wind','data_center','ev_charging'])
@pytest.mark.parametrize('human',[None,.056,.56,5.6,9.])
def test_four_vertical_rate_contract_is_exact_across_python_v10_v11(kind,human):
    base=getattr(pf,'create_generic_'+kind+'_reference')()
    pi=base if human is None else _resolve_user_inputs(project_type='Solar',base_inputs=base,interest_rate_pct=human)
    if human is not None:assert senior_rate_authority(pi)[1]==pytest.approx(human/100,abs=1e-17)
    catalogue={'F01':(lambda:pi,kind,None)}
    outcomes={arm:run_case('F01','canonical',arm,catalogue) for arm in ['off','v10_s12','s12_s3']}
    assert outcome_key(outcomes['off'])==outcome_key(outcomes['v10_s12'])==outcome_key(outcomes['s12_s3'])
    if outcomes['off']['verdict']=='FEASIBLE':
        assert outcomes['v10_s12']['v10']['native_solves']>0
        assert outcomes['s12_s3']['s3']['native_models']>0
    folder=os.environ.get('FINVAL_EVIDENCE_DIR')
    if folder:
        Path(folder).mkdir(parents=True,exist_ok=True)
        (Path(folder)/f'native-{kind}-{human}.json').write_text(json.dumps(outcomes,indent=2))
