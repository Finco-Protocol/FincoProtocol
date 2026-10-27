"""Exact-blob F01 attribution; never exempts arbitrary financial source drift."""
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE="cf7056de4078ca66afcf52265a9bacafe35586f7"
SOURCES={'app/input_adapter.py': '2db97ac44180d6e78c147dcfffb5daddb585c36f', 'app/persistence/projects_repository.py': 'f680039e6d13609e52c025c768c0a7b23a481734', 'app/persistence/workspace_repository.py': '3dbcd861d363d1c3f3ef1ff148f0ecae173612f7', 'app/services/project_library_service.py': '2ae7984416c52eee1b452be5c6a05611e4dca734', 'app/templates/partials/inputs_section.html': 'e0077a62ab2f8602c619005c3cb257a6a7d9a476', 'app/templates/partials/sheet_senior_debt.html': '76b0e2ff87b98d26590daceb68f2c2342caa605a', 'app/templates/partials/workspace_shell.html': '4d8a2d49345f53295e22a5a805cb4763c689ee5c', 'app/v2/grid_router.py': '0d1ab6c05b7d4f53f9d4a341818e107969bcccc0', 'app/v2/router.py': '2ec6b05a7d730e1034348da632d37efc6bfa9c3b', 'app/workbook/update_service.py': '2e39aca488df085662afb9b8e8f808ec304ae10c', 'main_web.py': 'e74e94503efda5bb3e0993de71b01bbe1122b892', '.github/workflows/finval_f01_acceptance.yml': '8b7b49a49583fc33c48d60cc55bd88ea9e88ef8d'}

def valid(repo=ROOT, sources=None):
    try:
        subprocess.run(["git","merge-base","--is-ancestor",BASE,"HEAD"],cwd=repo,check=True,capture_output=True)
        actual=sources if sources is not None else {p:(repo/p).read_bytes() for p in SOURCES}
        for path, expected in SOURCES.items():
            data=actual[path]
            if isinstance(data,str): data=data.encode()
            got=subprocess.check_output(["git","hash-object","--stdin"],input=data,cwd=repo).decode().strip()
            if got!=expected:
                from tests.fin_v2_3_scope import matches
                if not matches(path,data,repo=repo):return False
        return True
    except (OSError, KeyError, subprocess.CalledProcessError):return False
