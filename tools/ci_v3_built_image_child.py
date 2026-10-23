"""Independent descendant supervisor for run-built private CI containers."""
import sys
from pathlib import Path
import subprocess
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.ci_process_cleanup import enable_subreaper, finish_cleanup
from tools.ci_v3_schema import write_json

if __name__ == '__main__':
    enable_subreaper()
    code = subprocess.call([sys.executable, '-I', str(Path(__file__).with_name('ci_v3_real_child.py')), sys.argv[1]])
    cleanup = finish_cleanup()
    write_json(Path(sys.argv[1]).parent/'descendant-cleanup.json', cleanup)
    raise SystemExit(code if code else (0 if cleanup['cleanup_verified'] else 125))
