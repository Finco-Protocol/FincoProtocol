"""Dormant required-gate adapter. No active workflow imports or invokes this code.

Protected source-specific activation authority is mandatory. Rejected admission
selects sequential BEFORE work. A selected parallel failure is terminal.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

from tools.ci_v3_activation import select_mode
from tools.ci_v3_hosted_transport import GitHub, receive, sha, validate_run
from tools.ci_v3_schema import ContractError, canonical_bytes, read_json, require, write_json


def activation_check(root):
    activation=root['activation']
    expected={'.github/workflows/public_safety_and_smoke.yml','.github/workflows/ci_v3_required_job.yml',
              '.github/workflows/ci_public_job.yml'}
    require(set(root.get('workflow_files_sha256',{}))==expected
            and activation.get('workflow_files_sha256')==root['workflow_files_sha256'], 'mandatory workflow tree not reviewed')
    proof=root['accepted_pair_proof']
    require(root['accepted_control']['root_sha256']==proof['roots_sha256']['control'], 'accepted control differs from accepted hosted pair')
    receipt=proof['transports']['control']['receipts']['control']
    expected_anchor={'artifact_id':receipt['artifact']['id'],'artifact_digest':receipt['artifact']['digest'].removeprefix('sha256:'),
                     'job_id':receipt['job']['id'],'receipt_sha256':receipt['receipt_sha256']}
    require(root['accepted_control']['anchors']=={'control':expected_anchor}, 'accepted control artifact anchors changed')
    require(root['shadow_plugin_profile_sha256']==proof['accepted_shadow_plugin_profile_sha256'], 'accepted plugin profile changed')
    pin=root['activation_sha256']
    require(sha(canonical_bytes(activation))==pin, 'activation content pin mismatch')
    return select_mode(activation,proof,source=root['source'],workflow_sha256=root['workflow_sha256'],
        controller={'head':root['controller_head'],'tree':root['controller_tree']},
        root_sha256=pin,expected_root_sha256=pin)


def load_accepted_control(binding,destination):
    """Preserve the actual admitted bytes, including original JSON formatting."""
    from tools.ci_v3_hosted_controller import load_root
    raw=base64.b64decode(binding['root_b64'],validate=True)
    require(sha(raw)==binding['root_sha256'],'accepted control raw bytes changed')
    Path(destination).write_bytes(raw)
    return load_root(destination,binding['root_sha256'])


def verify_current_phases(root,bundle,project,received,output,api):
    """Authenticate the accepted full control, then compare this run's workers."""
    from tools.ci_v3_hosted_controller import context, load_bundle, load_root, make_plan, read_plan, validate_receipt
    from tools.ci_v3_phase_compare import compare,control_report
    from tools.ci_v3_pytest_config import semantic_plugin_profile
    from tools.ci_v3_schema import digest
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    binding=root['accepted_control']
    root_path=output/'accepted-control-root.json'
    control_root=load_accepted_control(binding,root_path)
    require(control_root['execution_mode']=='control', 'accepted control side missing')
    for key in ('source','controller_head','controller_tree','controller_files_sha256','image','bundle'):
        require(control_root[key]==root[key], 'accepted source/control bundle mismatch: '+key)
    control_bundle=load_bundle(api,control_root)
    transport=receive(api,control_root,control_root['run_id'],control_root['run_attempt'],binding['anchors'],
                      output/'accepted',{'control':'ci-v3-control'})
    require(transport['provenance_authenticated'] is True, 'control provenance missing')
    directory=output/'accepted/control'
    plan=read_json(directory/'plan.json')
    require(plan==make_plan(project,control_bundle), 'accepted control plan changed')
    ctx=context(control_root,control_bundle,plan,control_root['run_id'],control_root['run_attempt'])
    processes=[validate_receipt(directory,'control',binding['root_sha256'],ctx,control_root)]
    control=control_report(read_json(directory/'child/adapter.json'))
    native=[(directory/'child/native.xml').read_bytes()];reports=[]
    _,ctx,_=read_plan(Path(received)/'plan',root,root['_root_sha256'],bundle,project,root['run_id'],root['run_attempt'])
    for name in ('worker-0','worker-1','worker-2'):
        directory=Path(received)/name
        processes.append(validate_receipt(directory,name,root['_root_sha256'],ctx,root))
        report=read_json(directory/'child/adapter.json');reports.append(report)
        require(digest(semantic_plugin_profile(report['plugin_registrations']))==root['shadow_plugin_profile_sha256'],
                'unreviewed mandatory plugin registration')
        native.append((directory/'child/native.xml').read_bytes())
    result=compare(control,reports,native,processes)
    require(result['environment_equal'] is True,'mandatory runtime environment changed')
    require(bundle['isolation'].get('allowed_daemon_threads',{})=={},'survivor permissions forbidden')
    write_json(output/'phase-comparison.json',result)
    return result


def main(argv=None):
    from tools.ci_v3_hosted_controller import (aggregate,load_bundle,load_root,stage_names,
                                              validate_controller,validate_merge,write_outputs)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('route','verify'))
    for name in ('root','root-sha256','project','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    try:
        root=read_json(args.root)
        if args.stage=='route' and (root.get('enabled') is not True or root.get('activation',{}).get('rollback') is True):
            write_outputs({'execution_mode':'sequential'})
            write_json(args.output,{'execution_mode':'sequential','retry_on_parallel_failure':False})
            return 0
        root=load_root(args.root,args.root_sha256)
        require(root.get('execution_authority')=='mandatory','missing mandatory activation authority')
        require(activation_check(root)['mode']=='parallel','parallel activation rejected')
        api=GitHub();validate_controller(root);validate_merge(api,root)
        validate_run(api,root,int(os.environ['GITHUB_RUN_ID']),int(os.environ['GITHUB_RUN_ATTEMPT']))
        bundle=load_bundle(api,root)
        if args.stage=='route':
            require(os.environ.get('CI_V3_REQUESTED_HEAD')==root['source']['head'],'source input not authorized')
            write_outputs({'execution_mode':'parallel','tested_sha':root['source']['head'],
                'controller_sha':root['controller_head'],'root_sha256':args.root_sha256,
                'root_b64':base64.b64encode(Path(args.root).read_bytes()).decode(),'image':root['image']})
            write_json(args.output,{'execution_mode':'parallel','retry_on_parallel_failure':False})
        else:
            anchors=json.loads(os.environ['CI_V3_HOST_ANCHORS'])
            received=Path(args.output).parent/'required-received'
            transport=receive(api,root,root['run_id'],root['run_attempt'],anchors,received,stage_names(root))
            root['_root_sha256']=args.root_sha256
            proof=aggregate(root,args.root_sha256,bundle,args.project,received,args.output,
                            root['run_id'],root['run_attempt'],transport,service_api=api)
            require(proof.get('mandatory_execution_valid') is True,'required parallel proof incomplete')
        return 0
    except (ContractError,OSError,KeyError,TypeError,ValueError,subprocess.SubprocessError) as exc:
        write_json(Path(args.output).parent/'mandatory-rejection.json',{'mandatory_execution_valid':False,'reason':str(exc)})
        if args.stage=='route':
            write_outputs({'execution_mode':'sequential'})
            write_json(args.output,{'execution_mode':'sequential','reason':'pre-execution admission rejected: '+str(exc),
                                   'retry_on_parallel_failure':False})
            return 0
        return 1  # never rerun the full suite after selected parallel failure

if __name__=='__main__':
    raise SystemExit(main())
