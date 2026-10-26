"""Explicit positive test requests under the new mutation contract.

Never patches a client, validator or server. Security-negative tests keep direct
client.post calls. Existing financial/CAS/ownership assertions are unchanged.
"""
from http.cookies import SimpleCookie
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qsl, urlencode

from app.workbook.mutation_csrf import mutation_token

ROUTES = {
    '/v2/workbook/update': 'workbook-update',
    '/v2/workbook/export': 'workbook-export',
    '/v2/reference-seed/reset': 'reference-seed-reset',
    '/v2/workbook/grid/save': 'grid-save',
    '/v2/workbook/grid/cost-lines/save': 'grid-cost-lines-save',
    **{'/v2/workbook/scenarios/'+op:'scenario-'+op for op in ('create','select','rename','archive','update-overrides','remove-override')},
    **{'/v2/'+kind+'/line/'+op:kind+'-'+op for kind in ('capex','opex') for op in ('add','update','deactivate','reactivate','reorder')},
    '/v2/capex/contingency': 'capex-contingency',
}


def post_valid_mutation(client, url, *args, **kwargs):
    operation=ROUTES.get(urlsplit(str(url)).path)
    assert operation is not None,'Positive helper only admits inventoried model mutation routes'
    assert 'form' not in kwargs,'Browser callers use their real rendered/projection token'
    transport='json' if 'json' in kwargs else 'content' if 'content' in kwargs else 'data'
    pairs=None
    if transport=='content':
        raw=kwargs['content']
        pairs=parse_qsl(raw.decode() if isinstance(raw,bytes) else raw,keep_blank_values=True)
        values=dict(pairs)
    else:
        values=dict(kwargs.get(transport) or {})
    # A shared pre-existing field caller may select Capital Stack dynamically.
    # Forward its original request byte-for-byte: never issue, replace or add
    # its released token, including deliberately missing/invalid test tokens.
    if values.get('field_id')=='debt.financing.instruments':
        return client.post(url,*args,**kwargs)
    effective=client.build_request('POST',url,cookies=kwargs.get('cookies'),headers=kwargs.get('headers'))
    cookies=SimpleCookie();cookies.load(effective.headers.get('cookie',''))
    request=SimpleNamespace(cookies={k:v.value for k,v in cookies.items()},state=SimpleNamespace())
    values['csrf_token']=mutation_token(request,str(values.get('project','')),operation)
    kwargs[transport]=(urlencode([(k,v) for k,v in pairs if k!='csrf_token']+[('csrf_token',values['csrf_token'])])
                       if pairs is not None else values)
    return client.post(url,*args,**kwargs)
