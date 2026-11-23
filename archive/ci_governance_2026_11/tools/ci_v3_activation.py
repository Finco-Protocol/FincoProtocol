"""Protected mandatory-mode selector: sequential default, explicit rollback, exact authority.

The active router preserves stable mandatory contexts and stays sequential
unless independently approved source-specific admission is complete. A rejected or missing
activation chooses sequential before execution. Failure AFTER parallel selection
is a mandatory failure, never an automatic second full-suite execution.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from tools.ci_v3_schema import ContractError, check_seal, read_json, require, write_json


def select_mode(root, proof, *, source, workflow_sha256, controller, root_sha256, expected_root_sha256):
    if root.get('enabled') is not True or root.get('rollback') is True:
        return {'mode':'sequential','reason':'disabled or explicit rollback','retry_on_parallel_failure':False}
    require(root_sha256 == expected_root_sha256 and len(root_sha256)==64, 'activation authority pin mismatch')
    require(root.get('schema')==1 and root.get('kind')=='ci-v3-mandatory-activation', 'activation schema')
    require(root.get('deployment_review_reference'), 'mandatory routing deployment has not been reviewed')
    refs = root.get('owner_references',{})
    require(set(refs)=={'Financial','Security','CI'} and all(isinstance(v,str) and v.strip() for v in refs.values()),
            'required activation/protected-source reviews absent')
    require(root.get('source')==source and root.get('controller')==controller
            and root.get('mandatory_workflow_sha256')==workflow_sha256, 'activation source/controller/workflow mismatch')
    if root.get('admission_mode') == 'direct-production-v1':
        require(root.get('workflow_governance_approved') is True and root.get('required_contexts_preserved') is True
                and root.get('browser_acceptance_preserved') is True, 'direct workflow governance incomplete')
        from tools.ci_v3_direct import validate_profile
        return validate_profile(root,proof,source)
    require(root.get('admission_mode','accepted-pair')=='accepted-pair','unsupported activation profile')
    check_seal(proof,'ci-v3-pair-acceptance')
    require(proof.get('digest')==root.get('accepted_pair_digest') and proof.get('source')==source,
            'accepted hosted evidence substituted/stale')
    require(proof.get('technical_validity') is True and proof['phase_comparison'].get('phase_equivalent') is True
            and proof['phase_comparison'].get('process_cleanup_valid') is True
            and proof['phase_comparison'].get('native_junit_valid') is True, 'technical admission incomplete')
    require(proof['performance'].get('performance_success') is True
            and proof['performance'].get('observed_speedup',0)>=2, 'performance objective not accepted')
    require(set(proof.get('transports',{}))=={'control','shadow'}
            and all(t.get('provenance_authenticated') is True for t in proof['transports'].values()),
            'unauthenticated hosted acceptance')
    require(root.get('workflow_governance_approved') is True and root.get('required_contexts_preserved') is True
            and root.get('browser_acceptance_preserved') is True, 'workflow governance incomplete')
    require(root.get('nonpass_policy_sha256') and root.get('isolation_policy_sha256')
            and root.get('environment_decision_sha256') and root.get('daemon_lifecycle_review_reference'),
            'activation policy/lifecycle bindings missing')
    bindings = {'nonpass_policy_sha256':'nonpass', 'isolation_policy_sha256':'isolation',
                'environment_decision_sha256':'environment'}
    for field, decision in bindings.items():
        require(root[field] == proof['accepted_decisions'][decision]['sha256'], 'activation '+decision+' decision differs')
    require(root['daemon_lifecycle_review_reference'] == proof['accepted_decisions']['daemon_lifecycle']['reference'],
            'activation lifecycle review differs')
    return {'mode':'parallel','reason':'exact protected activation authority and accepted pair',
            'retry_on_parallel_failure':False,'activation_root_sha256':root_sha256,
            'accepted_pair_digest':proof['digest']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','root-sha256','proof','source-head','source-tree','workflow-sha256','controller-head','controller-tree','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    try:
        raw=Path(args.root).read_bytes()
        actual=hashlib.sha256(raw).hexdigest()
        require(actual==args.root_sha256,'protected activation bytes changed')
        value=select_mode(read_json(args.root),read_json(args.proof),
            source={'head':args.source_head,'tree':args.source_tree},workflow_sha256=args.workflow_sha256,
            controller={'head':args.controller_head,'tree':args.controller_tree},
            root_sha256=actual,expected_root_sha256=args.root_sha256)
    except (ContractError,OSError,KeyError,TypeError,ValueError) as exc:
        value={'mode':'sequential','reason':'activation rejected: '+str(exc),'retry_on_parallel_failure':False}
    write_json(args.output,value)
    if os.environ.get('GITHUB_OUTPUT'):
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
            stream.write('execution_mode='+value['mode']+'\n')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
