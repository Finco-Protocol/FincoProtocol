"""Prospective, run-specific allocation checks; ceilings never grant authority."""
from tools.ci_v3_schema import require

ALLOCATIONS = {'shadow':350, 'control':230}


def validate_spending(root):
    value = root.get('budget_authorization',{})
    require(value.get('approved') is True and value.get('review_reference')
            and value.get('source') == root['source'], 'run-specific spending approval absent/stale')
    require(value.get('control_run_id') != value.get('shadow_run_id')
            and all(type(value.get(k)) is int and value[k]>0 for k in ('control_run_id','shadow_run_id')),
            'exact distinct control/shadow run IDs required')
    side=root['execution_mode']
    require(value[side+'_run_id']==root['run_id'] and value.get(side+'_attempt')==root['run_attempt'],
            'spending authorization names another run/attempt')
    require(value.get('shadow_max_minutes')==350 and value.get('control_max_minutes')==230
            and value.get('pair_max_minutes')==590, 'fixed workflow allocations must be authorized exactly')
    require(value.get('ancillary_accounting')=='separately-authorized'
            and type(value.get('ancillary_max_minutes')) is int and value['ancillary_max_minutes']>=0,
            'separate mandatory/browser/governance accounting required')
    require(value.get('ancillary_review_reference'), 'ancillary spending or pre-existing cost classification absent')
    return value


def validate_nonpass_decisions(policy,decisions,source):
    require(decisions.get('source')==source,'nonpass decisions belong to another source')
    expected=policy['allowed_nonpass'];records=decisions.get('records',{})
    require(set(records)==set(expected),'exact per-record Financial/CI decisions missing or foreign')
    for node,record in expected.items():
        value=records[node]
        require(value.get('record')==record,'obsolete nonpass status/reason: '+node)
        require(all(isinstance(value.get(role),str) and value[role].strip() for role in ('Financial','CI')),
                'nonpass owner decision missing: '+node)
    return decisions
