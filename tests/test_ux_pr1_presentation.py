"""Execute the focused frontend assertions (not just Node's file-level harness)."""
import subprocess
from pathlib import Path

def test_ux_pr1_navigation_precision_and_legacy_disclosure():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','frontend/src/app/__tests__/uxPr1.test.mjs'],cwd=root,text=True,capture_output=True)
    assert result.returncode==0, result.stdout+result.stderr
    assert 'tests 4' in result.stdout and 'pass 4' in result.stdout
