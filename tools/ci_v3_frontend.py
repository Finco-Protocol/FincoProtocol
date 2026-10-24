"""Locked frontend tools for private run-built test sources; never installs in tests."""
from pathlib import Path
import hashlib,json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_frontend(project, bundle=Path('/opt/ci-v3/frontend')):
    project=Path(project);bundle=Path(bundle)
    frontend=project/'frontend'
    if not (frontend/'package.json').is_file():return None
    manifest=bundle/'identity.json'
    if not manifest.is_file():raise ValueError('locked frontend runtime missing; no skip fallback')
    record=json.loads(manifest.read_text())
    for name in ['package.json','package-lock.json']:
        if sha(frontend/name)!=record[name]:raise ValueError('frontend runtime/source input mismatch')
    modules=bundle/'node_modules'
    if sha(modules/'.package-lock.json')!=record['installed_lock_sha256']:
        raise ValueError('frontend installed lock mismatch')
    if sha(modules/'typescript/bin/tsc')!=record['typescript_entry_sha256']:
        raise ValueError('frontend compiler bytes mismatch')
    destination=frontend/'node_modules'
    if destination.exists() or destination.is_symlink():raise ValueError('unexpected subject frontend dependencies')
    # Dependencies stay on the immutable read-only root; only the private source
    # receives a link. No network, scripts, source build or token reaches tests.
    destination.symlink_to(modules,target_is_directory=True)
    return record


def frontend_record(project=Path('.')):
    frontend=Path(project)/'frontend';package=frontend/'package.json'
    if not package.is_file():return None
    result={'package_sha256':sha(package),'lock_sha256':sha(frontend/'package-lock.json')}
    marker=frontend/'node_modules/.package-lock.json';compiler=frontend/'node_modules/typescript/bin/tsc'
    result['installed_lock_sha256']=sha(marker) if marker.is_file() else None
    result['typescript_entry_sha256']=sha(compiler) if compiler.is_file() else None
    result['typescript_version']=json.loads((frontend/'node_modules/typescript/package.json').read_text())['version'] if compiler.is_file() else None
    return result


def frontend_image_record(bundle=Path('/opt/ci-v3/frontend')):
    path=Path(bundle)/'identity.json'
    return json.loads(path.read_text()) if path.is_file() else None
