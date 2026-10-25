"""Explicit migration of positive Run/Clone test callers to session-bound CSRF.

This does not alter TestClient or server validation. Negative security tests call
client.post directly. Existing rejection/CAS tests still reach their own guards.
"""
from types import SimpleNamespace
from urllib.parse import urlsplit
from http.cookies import SimpleCookie

from app.workbook.financing_csrf import issue_token


def post_valid_csrf(client, url, *args, **kwargs):
    # Browser API requests use the actual legacy form token contract.
    if "form" in kwargs:
        form = dict(kwargs["form"])
        parsed = urlsplit(str(url))
        assert parsed.path == "/v2/workbook/run"
        boot = client.get(parsed.scheme + "://" + parsed.netloc + "/v2/workbook",
                          params={"project": form["project"]})
        from bs4 import BeautifulSoup
        run_form = BeautifulSoup(boot.text(), "html.parser").select_one("#v2-canonical-run-form")
        assert run_form is not None
        form.pop("run_csrf_token", None)
        form["csrf_token"] = run_form.select_one('[name="run_csrf_token"]')["value"]
        kwargs["form"] = form
        return client.post(url, *args, **kwargs)
    # Ask httpx to resolve its actual jar, per-request cookies and explicit
    # Cookie-header precedence. An explicit Cookie header REPLACES the jar.
    effective = client.build_request("POST", url, cookies=kwargs.get("cookies"),
                                     headers=kwargs.get("headers"))
    parsed_cookies = SimpleCookie()
    parsed_cookies.load(effective.headers.get("cookie", ""))
    request = SimpleNamespace(cookies={k: v.value for k, v in parsed_cookies.items()},
                              state=SimpleNamespace())
    data = dict(kwargs.get("data") or {})
    if str(url).split("?")[0] == "/v2/workbook/run":
        data.pop("run_csrf_token", None)
        token = issue_token(request, data.get("project", ""), purpose="workbook-run-v1")
    elif str(url).startswith("/library/clone/"):
        token = issue_token(request, "", purpose="library-clone-v1")
    else:
        raise AssertionError("CSRF helper is restricted to canonical Run/Clone")
    data["csrf_token"] = token
    kwargs["data"] = data
    return client.post(url, *args, **kwargs)
