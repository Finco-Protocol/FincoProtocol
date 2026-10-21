"""GET-only service client, independent digest checks and fail-closed pagination."""
import base64
import hashlib
import urllib.error

import pytest

from tools.ci_v3_hosted_transport import GitHub
from tools.ci_v3_schema import ContractError


class Response:
    def __init__(self,data):self.data=data
    def read(self,n):return self.data[:n]
    def __enter__(self):return self
    def __exit__(self,*args):pass


class Opener:
    def __init__(self,redirect):self.redirect=redirect;self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request)
        if len(self.requests)==1:raise urllib.error.HTTPError(request.full_url,302,'Found',{'Location':self.redirect},None)
        return Response(b'archive fixture')


def test_api_credentials_are_not_forwarded_to_artifact_storage():
    api=GitHub(token='fixture-not-a-credential');api.opener=Opener('https://fixture.blob.core.windows.net/archive')
    assert api.raw('/repos/owner/project/actions/artifacts/12/zip',archive=True)==b'archive fixture'
    assert api.opener.requests[0].get_header('Authorization')=='Bearer fixture-not-a-credential'
    assert api.opener.requests[1].get_header('Authorization') is None
    assert all(r.get_method()=='GET' for r in api.opener.requests)


@pytest.mark.parametrize('url',['http://fixture.blob.core.windows.net/a','https://evil.invalid/a','https://user'+'@fixture.blob.core.windows.net/a'])
def test_untrusted_redirects_rejected(url):
    api=GitHub();api.opener=Opener(url)
    with pytest.raises(ContractError,match='redirect'):api.raw('/repos/owner/project/actions/artifacts/12/zip',archive=True)
    assert len(api.opener.requests)==1


def test_http_error_never_becomes_empty_success():
    api=GitHub()
    class Failure:
        def open(self,request,timeout):raise urllib.error.HTTPError(request.full_url,403,'Forbidden',{},None)
    api.opener=Failure()
    with pytest.raises(ContractError,match='GET failed'):api.get('/repos/owner/project/actions/runs/1')


def test_pagination_and_incomplete_metadata_fail_closed(monkeypatch):
    api=GitHub();calls=[]
    def get(path):
        calls.append(path)
        return {'total_count':101,'jobs':list(range(100)) if path.endswith('&page=1') else [100]}
    monkeypatch.setattr(api,'get',get)
    assert len(api.listing('/repos/owner/project/actions/runs/1/jobs','jobs'))==101
    assert len(calls)==2
    monkeypatch.setattr(api,'get',lambda path:{'total_count':2,'jobs':[1]})
    with pytest.raises(ContractError,match='incomplete'):api.listing('/repos/owner/project/actions/runs/1/jobs','jobs')


def test_git_content_identity_is_verified(monkeypatch):
    data=b'approved fixture';git_sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    api=GitHub();response={'type':'file','encoding':'base64','content':base64.b64encode(data).decode(),'sha':git_sha}
    monkeypatch.setattr(api,'get',lambda path:response)
    assert api.content('owner/project','a'*40,'inventory.json')==data
    response['sha']='f'*40
    with pytest.raises(ContractError,match='blob substitution'):api.content('owner/project','a'*40,'inventory.json')


def test_duplicate_service_json_keys_rejected(monkeypatch):
    api=GitHub();monkeypatch.setattr(api,'raw',lambda path:b'{"id":1,"id":2}')
    with pytest.raises(ContractError,match='duplicate JSON'):api.get('/repos/owner/project/actions/runs/1')


@pytest.mark.parametrize('fault',[None,'identity','truncated'])
def test_large_inventory_contents_use_immutable_git_blob(monkeypatch,fault):
    data=b'large-file API shape without allocating a giant fixture'
    blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    api=GitHub();calls=[]
    def get(path):
        calls.append(path)
        if '/contents/' in path:return {'type':'file','encoding':'none','content':'','sha':blob}
        return {'sha':'f'*40 if fault=='identity' else blob,'encoding':'base64',
                'content':base64.b64encode(data).decode(),'size':len(data)+(1 if fault=='truncated' else 0)}
    monkeypatch.setattr(api,'get',get)
    if fault:
        with pytest.raises(ContractError):api.content('owner/project','a'*40,'inventory.json')
    else:
        assert api.content('owner/project','a'*40,'inventory.json')==data
        assert calls[-1].endswith('/git/blobs/'+blob)


def test_archive_response_limit_enforced(monkeypatch):
    api=GitHub()
    class Large:
        def open(self,request,timeout):
            class Oversized(Response):
                def read(self,n):return b'x'*11
            return Oversized(b'')
    # Avoid allocating half a gigabyte just to test the bound.
    from tools import ci_v3_hosted_transport as module
    monkeypatch.setattr(module,'MAX_ARCHIVE',10)
    api.opener=Large()
    with pytest.raises(ContractError,match='too large'):api.raw('/repos/owner/project/actions/artifacts/12/zip')
