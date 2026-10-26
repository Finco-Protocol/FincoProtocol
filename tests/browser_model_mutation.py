"""Read real Legacy form tokens using an existing authenticated browser request.

No signing, fabricated cookies, validator patches or automatic POST rewriting.
Only explicit positive browser callers use this test helper.
"""
from urllib.parse import urlencode

from bs4 import BeautifulSoup


def rendered_form_token(request, root, project, path, *, field_id=None):
    sheets = {"/v2/workbook/update": "debt",
              "/v2/workbook/scenarios/create": "scenarios",
              "/v2/workbook/scenarios/select": "scenarios"}
    assert path in sheets, "Only inventoried Legacy positive mutations are admitted"
    if path == "/v2/workbook/update":
        assert field_id and field_id != "debt.financing.instruments", "Capital Stack retains its own token domain"
    response = request.get(root + "/v2/workbook?" + urlencode({"project": project, "sheet": sheets[path]}))
    assert response.ok, response.status
    soup = BeautifulSoup(response.text(), "html.parser")
    for form in soup.find_all("form", attrs={"hx-post": path}):
        resource = form.find("input", attrs={"name": "project"})
        if resource is None or resource.get("value") != project:
            continue
        if field_id:
            field = form.find("input", attrs={"name": "field_id"})
            if field is None or field.get("value") != field_id:
                continue
        controls = form.find_all("input", attrs={"type": "hidden", "name": "csrf_token"})
        assert len(controls) == 1 and controls[0].get("value")
        return controls[0]["value"]
    raise AssertionError("No real authenticated Legacy mutation form for the requested project/field")
