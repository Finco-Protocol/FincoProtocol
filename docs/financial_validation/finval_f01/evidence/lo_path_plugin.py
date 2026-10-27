"""Local environment adapter: resolve installed soffice before the test narrows PATH.

No test assertion, argument, environment, return value or skip is changed.
"""
import shutil
import subprocess
SOFFICE=shutil.which('soffice')
_original_run=subprocess.run

def pytest_configure(config):
    def run(args,*a,**kw):
        if isinstance(args,(list,tuple)) and args and args[0]=='soffice' and SOFFICE:
            args=[SOFFICE,*args[1:]]
        return _original_run(args,*a,**kw)
    subprocess.run=run

def pytest_unconfigure(config):
    subprocess.run=_original_run
