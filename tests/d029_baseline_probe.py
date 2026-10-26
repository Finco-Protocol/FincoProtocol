"""D-029 released-baseline diagnostic; isolated fixtures and real canonical engine.

Not a pytest test or production service. No intent-enabled HTTP guarantee is claimed.
"""
from __future__ import annotations
import os,sys,json,math,time,threading,traceback
from pathlib import Path
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT = None  # Set explicitly by the CLI; never write to application data.
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['FINCO_MODEL_EXECUTION_MODE']='thread' # released dev/test scheduler; canonical finance unchanged
os.environ['FINCO_NATIVE_V10_RUN']='off';os.environ['FINCO_NATIVE_V11_RUN']='off'
import pytest
from tests.test_model_decision_workspace_v2 import env,tokens
from tests.test_model_financing_f2 import run
from tests.test_model_credit_decision_v3_real_runs import history,last
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.update_service import WorkbookUpdateService
from app.workbook.registry import WORKBOOK
from app.workbook.financing_csrf import issue_token
from types import SimpleNamespace

USER='decision-user'

def nonfinite(value,path=''):
 out=[]
 if isinstance(value,float) and not math.isfinite(value):out.append({'path':path,'repr':repr(value)})
 elif isinstance(value,dict):
  for k,v in value.items():out+=nonfinite(v,path+'.'+str(k))
 elif isinstance(value,(tuple,list)):
  for i,v in enumerate(value):out+=nonfinite(v,path+f'[{i}]')
 return out

def text(response):
 from bs4 import BeautifulSoup
 return BeautifulSoup(response.text,'html.parser').get_text(' ',strip=True)[:1800]

@contextmanager
def fixture(name):
 mp=pytest.MonkeyPatch();p=OUT/'db'/name;p.mkdir(parents=True,exist_ok=True)
 gen=env.__wrapped__(p,mp)
 try:yield next(gen),mp
 finally:
  try:next(gen,None)
  finally:mp.undo()

def form(e,r):
 page=e.client.get('/v2/workbook',params={'project':r.project_code})
 req=SimpleNamespace(cookies=e.client.cookies,state=SimpleNamespace())
 return {'project':r.project_code,**tokens(page.text),'csrf_token':issue_token(req,r.project_code,purpose='workbook-run-v1')}

def submit(e,data):
 return e.client.post('/v2/workbook/run',headers={'HX-Request':'true'},data=dict(data))

def edit(e,r,raw,field='revenue.ppa.base_tariff'):
 page=e.client.get('/v2/workbook',params={'project':r.project_code})
 from tests.model_mutation_csrf import post_valid_mutation
 return post_valid_mutation(e.client,'/v2/workbook/update',headers={'HX-Request':'true'},data={'project':r.project_code,'field_id':field,'value':raw,**tokens(page.text)})

def install_counter(mp,gate=False):
 import app.api.project_runner as pr
 orig=pr.run_project;lock=threading.Lock();calls=[];entered=threading.Event();release=threading.Event()
 def counted(*args,**kwargs):
  with lock:
   calls.append({'entered_at':time.monotonic(),'completed':False,'effective_tariff':getattr(getattr(kwargs.get('project_inputs_override'),'revenue',None),'ppa_base_tariff',None)});idx=len(calls)-1
  entered.set()
  if gate and not release.wait(15):raise RuntimeError('private event deadline expired')
  try:result=orig(*args,**kwargs)
  except Exception as exc:
   with lock:calls[idx].update(error_type=type(exc).__name__,error_message=str(exc))
   raise
  with lock:
   calls[idx].update(completed=True,nonfinite=nonfinite(result),kpis=result.get('kpis'))
  return result
 mp.setattr(pr,'run_project',counted)
 return calls,entered,release

def summary(e,r):
 ws=get_workspace_state(USER,r.project_id);entries=history(r)
 return {'history_count':len(entries),'history_ids':[x.history_id for x in entries],
         'snapshot_ids':[x.runtime_snapshot_id for x in entries],
         'composite_hashes':[x.composite_hash for x in entries],
         'dirty':ws.dirty,'last_snapshot_id':ws.last_runtime_snapshot_id,
         'last_runtime_summary':ws.last_runtime_summary,
         'nonfinite_persisted':nonfinite([__import__('dataclasses').asdict(x) for x in entries])}

def lifecycle(mode):
 with fixture('lifecycle-'+mode) as (e,mp):
  r=e.create('solar');data=form(e,r);before=summary(e,r)
  gate=mode in ('concurrent','save-during-run','busy','unknown-outcome')
  calls,entered,release=install_counter(mp,gate=gate)
  responses=[];transport_error=None
  if mode=='single':
   responses=[submit(e,data)]
  elif mode=='sequential':
   responses=[submit(e,data),submit(e,data)]
  elif mode=='concurrent':
   with ThreadPoolExecutor(2) as pool:
    a=pool.submit(submit,e,data);assert entered.wait(10)
    b=pool.submit(submit,e,data)
    deadline=time.monotonic()+10
    while len(calls)<2 and time.monotonic()<deadline:time.sleep(.01)
    release.set();responses=[a.result(25),b.result(25)]
  elif mode=='save-during-run':
   with ThreadPoolExecutor(1) as pool:
    a=pool.submit(submit,e,data);assert entered.wait(10)
    saved=edit(e,r,'58');responses.append(saved);release.set();responses.append(a.result(25))
  elif mode=='stale-cas':
   responses=[edit(e,r,'58'),submit(e,data)]
  elif mode=='missing-csrf':
   data.pop('csrf_token');responses=[submit(e,data)]
  elif mode=='cross-session':
   from app.auth import COOKIE_NAME,create_session_token
   previous=e.client.cookies.get(COOKIE_NAME)
   e.client.cookies.set(COOKIE_NAME,create_session_token(user_id=USER,username='admin'))
   assert e.client.cookies.get(COOKIE_NAME)!=previous
   responses=[submit(e,data)]
  elif mode=='busy':
   mp.setenv('FINCO_MODEL_EXECUTION_CONCURRENCY','1')
   with ThreadPoolExecutor(1) as pool:
    a=pool.submit(submit,e,data);assert entered.wait(10)
    responses.append(submit(e,data));release.set();responses.append(a.result(25))
  elif mode=='lost-response':
   import httpx
   transport=e.client._transport;original_transport=transport.handle_request
   def lose_after_commit(request):
    response=original_transport(request)
    if request.method=='POST' and request.url.path=='/v2/workbook/run':
     raise httpx.ReadError('private simulated response loss after server completion',request=request)
    return response
   mp.setattr(transport,'handle_request',lose_after_commit)
   try:submit(e,data)
   except httpx.ReadError as exc:transport_error=type(exc).__name__
  elif mode=='unknown-outcome':
   # Existing runtime timeout error path, without reducing/changing financial
   # iteration settings or the configured executor deadline: fault-inject only
   # the transport-facing wait result, then let the real engine finish.
   import app.runtime.model_execution as me
   original=me.run_model_process
   pending=[]
   async def uncertain(fn,*args,**kwargs):
    import asyncio
    task=asyncio.create_task(original(fn,*args,**kwargs));pending.append(task)
    while not entered.is_set():await asyncio.sleep(.01)
    raise me.ModelExecutionTimeout()
   mp.setattr(me,'run_model_process',uncertain)
   responses.append(submit(e,data));release.set()
   deadline=time.monotonic()+15
   while (not calls or not calls[0]['completed']) and time.monotonic()<deadline:time.sleep(.01)
  else:raise ValueError(mode)
  return {'mode':mode,'executor_mode':'released thread fallback; actual canonical engine',
          'before':before,'responses':[{'status':x.status_code,'text':text(x)} for x in responses],
          'engine_calls':calls,'transport_error':transport_error,'after':summary(e,r)}

if __name__ == '__main__':
 import argparse
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--case',required=True,choices=('single','sequential','concurrent','save-during-run','stale-cas','missing-csrf','cross-session','busy','lost-response','unknown-outcome'))
 args=parser.parse_args()
 OUT=args.output.resolve();OUT.mkdir(parents=True,exist_ok=True)
 result=lifecycle(args.case)
 destination=OUT/('lifecycle-'+args.case+'.json')
 destination.write_text(json.dumps(result,indent=2,sort_keys=True,default=str,allow_nan=False),encoding='utf-8')
 print('EVIDENCE_SAVED',destination)
