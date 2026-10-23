"""Actual tiny pytest processes with explicitly mocked GitHub service metadata."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import zipfile

from tools.ci_v3_hosted_controller import STAGES, context, receipt
from tools.ci_v3_hosted_transport import sha
from tools.ci_v3_isolation import constrained_plan
from tools.ci_v3_process_observer import observe
from tools.ci_v3_real_contract import environment_record, file_sha
from tools.ci_v3_schema import canonical_bytes, read_json, seal, write_json
from tools.ci_v3_shadow_local import ARTIFACTS, bridge_worker
from tools.ci_v3_synthetic_project import create_project


class FixtureAPI:
    authenticated_service = False

    def __init__(self):
        self.payloads = {}; self.data = {}; self.contents = {}

    def get(self, path):
        return deepcopy(self.data[path])

    def raw(self, path, archive=False):
        return self.payloads[int(path.split('/')[-2])]

    def content(self, repo, revision, path):
        return self.contents[(repo, revision, path)]

    def listing(self, path, key):
        return deepcopy(self.data[path][key])


def archive(path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for file in sorted(Path(path).rglob('*')):
            if file.is_file(): z.write(file, file.relative_to(path).as_posix())
    return buffer.getvalue()


def real_bundle(directory):
    project = directory / 'project'
    inventory, policy, weights = create_project(project)
    env = environment_record(); env['pytest_plugin_autoload'] = '1'
    env['runtime_fingerprint']['pytest_plugin_autoload'] = '1'
    isolation = seal({'schema':3,'kind':'ci-v3-isolation-policy','source':inventory['source'],
        'profile':'docker-no-network-private-workspace-v1','fixture_tree_reviewed':True,
        'review_reference':'synthetic fixture only, not FINCO approval',
        'modules':{name:{'sha256':file_sha(project/name),'reviewed':True,'rationale':'tiny explicit fixture',
                        'mode':'runner-private'} for name in inventory['modules']}})
    bundle = {'inventory':inventory,'policy':policy,'weights':weights,'environment':env,'isolation':isolation}
    workflow = b'name: transport fixture only\n'
    root = {'schema':3,'kind':'ci-v3-hosted-admission','enabled':True,'review_reference':'TEST FIXTURE ONLY',
        'execution_mode':'shadow','target_calibration':{'ceiling_s':.6,'statistic':'maximum','samples':3},
        'owner_decisions':['Financial','Security','CI'],'experiment_pairs':1,'workers':3,'run_id':123,'run_attempt':2,'repository':inventory['repository'],
        'source':inventory['source'],'controller_head':'a'*40,'controller_tree':'b'*40,'workflow_head':'c'*40,
        'workflow_path':'.github/workflows/ci_v3_shadow.yml','workflow_sha256':sha(workflow),
        'image':'example.invalid/fixture@sha256:'+'d'*64,'pr_number':None,
        'merge_proof':{'mode':'main-head','merge_sha':None,'merge_tree':None},'controller_files_sha256':{},
        'bundle':{'repository':inventory['repository'],'revision':'e'*40,
                  'files':{n:{'path':n+'.json','sha256':sha(canonical_bytes(v))} for n,v in bundle.items()}}}
    root['nonpass_owner_decisions']={'source':inventory['source'],'records':{
        node:{'record':record,'Financial':'SYNTHETIC LOCAL VALIDATION ONLY','CI':'SYNTHETIC LOCAL VALIDATION ONLY'}
        for node,record in policy['allowed_nonpass'].items()}}
    root['budget_authorization']={'approved':True,'review_reference':'SYNTHETIC ONLY','source':inventory['source'],
        'control_run_id':122,'control_attempt':1,'shadow_run_id':123,'shadow_attempt':2,
        'shadow_max_minutes':350,'control_max_minutes':230,'pair_max_minutes':590,
        'ancillary_accounting':'separately-authorized','ancillary_max_minutes':315,'ancillary_review_reference':'SYNTHETIC ONLY'}
    root_sha=sha(canonical_bytes(root));plan=constrained_plan(project,inventory,policy,weights,isolation)
    ctx=context(root,bundle,plan,123,2);paths={}
    def execute(name):
        output=directory/'payloads'/name;output.mkdir(parents=True)
        request={'mode':'discover' if name=='plan' else 'worker','context':ctx,'project':str(project),
            'worker':None if name=='plan' else name,'inventory':inventory,
            'owned_modules':[m for m,w in plan['module_workers'].items() if w==name]}
        observed=observe(request,output/'child',20)
        assert observed['normal_successful_exit'],observed
        if name!='plan': observed=bridge_worker(output/'child',observed,ctx)
        else:
            write_json(output/'plan.json',plan)
            write_json(output/'collection.json',read_json(output/'child/adapter.json')['collection'])
            observed['plan_sha256']=file_sha(output/'plan.json');observed['collection_sha256']=file_sha(output/'collection.json')
            observed['artifact_sha256']={p.name:file_sha(p) for p in (output/'child').iterdir() if p.name in ARTIFACTS and p.is_file()}
        value=receipt(output,name,root_sha,ctx,observed,root);value['synthetic_only']=True
        write_json(output/'receipt.json',value)
        return output
    paths['plan']=execute('plan')
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending={name:pool.submit(execute,name) for name in STAGES if name!='plan'}
        paths.update({name:future.result() for name,future in pending.items()})
    api=FixtureAPI();repo=root['repository'];prefix='/repos/'+repo
    run={'id':123,'run_attempt':2,'repository':{'full_name':repo,'id':99},'head_sha':root['workflow_head'],
         'workflow_id':77,'event':'workflow_dispatch','conclusion':None,'status':'in_progress'}
    api.data[prefix+'/actions/runs/123']=deepcopy(run);api.data[prefix+'/actions/runs/123/attempts/2']=run
    api.data[prefix+'/actions/workflows/77']={'id':77,'path':root['workflow_path']}
    api.data[prefix+'/git/commits/'+root['source']['head']]={'sha':root['source']['head'],'tree':{'sha':root['source']['tree']}}
    api.data[prefix+'/git/commits/'+root['controller_head']]={'sha':root['controller_head'],'tree':{'sha':root['controller_tree']}}
    api.data[prefix+'/branches/main']={'commit':{'sha':root['source']['head']}}
    api.contents[(repo,root['workflow_head'],root['workflow_path'])]=workflow
    for n,v in bundle.items(): api.contents[(repo,'e'*40,n+'.json')]=canonical_bytes(v)
    jobs=[];artifacts=[];anchors={}
    for i,name in enumerate(STAGES):
        api.payloads[10+i]=archive(paths[name]);data=api.payloads[10+i]
        jobs.append({'id':100+i,'name':STAGES[name],'run_id':123,'run_attempt':2,'head_sha':root['workflow_head'],
            'status':'completed','conclusion':'success','started_at':'2026-10-21T10:00:00Z','completed_at':'2026-10-21T10:10:00Z'})
        artifacts.append({'id':10+i,'name':f'ci-v3-{name}-123-2','size_in_bytes':len(data),'expired':False,
            'digest':'sha256:'+sha(data),'created_at':'2026-10-21T10:09:00Z','updated_at':'2026-10-21T10:09:01Z',
            'workflow_run':{'id':123,'head_sha':root['workflow_head'],'repository_id':99}})
        anchors[name]={'artifact_id':10+i,'artifact_digest':sha(data),'receipt_sha256':file_sha(paths[name]/'receipt.json'),'job_id':100+i}
    api.data[prefix+'/actions/runs/123/attempts/2/jobs']={'total_count':len(jobs),'jobs':jobs}
    api.data[prefix+'/actions/runs/123/artifacts']={'total_count':len(artifacts),'artifacts':artifacts}
    return {'api':api,'root':root,'root_sha':root_sha,'bundle':bundle,'project':project,'paths':paths,'anchors':anchors,
        'profile':'windows-job-kill-on-close' if os.name=='nt' else 'posix-process-group','context':ctx}
