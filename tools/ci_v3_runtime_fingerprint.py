"""Read-only environment capture; never grants equivalence or owner approval."""
import hashlib,importlib.metadata,json,os,platform,shutil,subprocess,sys
from functools import lru_cache
from pathlib import Path

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def command(args):
 try:
  p=subprocess.run(args,capture_output=True,text=True,timeout=15)
  return {'exit_code':p.returncode,'output':(p.stdout+p.stderr).strip()}
 except (OSError,subprocess.TimeoutExpired) as exc:return {'unavailable':type(exc).__name__}

@lru_cache(maxsize=1)
def _static_capture():
 packages=[];native={}
 for d in importlib.metadata.distributions():
  record=d.read_text('RECORD')
  packages.append({'name':d.metadata.get('Name'),'version':d.version,'record_sha256':hashlib.sha256(record.encode()).hexdigest() if record else None})
  for f in d.files or []:
   if '.so' in str(f):
    p=Path(d.locate_file(f)).resolve()
    if p.is_file():native[str(p)]=sha(p)
 cpu={}
 try:
  for line in Path('/proc/cpuinfo').read_text().splitlines():
   if ':' in line:
    key,value=map(str.strip,line.split(':',1))
    if key in ['vendor_id','model name','flags']:cpu[key]=value
 except OSError:pass
 limits={}
 for n in ['cpu.max','memory.max','pids.max']:
  try:limits[n]=Path('/sys/fs/cgroup',n).read_text().strip()
  except OSError as exc:limits[n]={'unavailable':type(exc).__name__}
 tools={}
 for name,args in {'git':['--version'],'node':['--version'],'npm':['--version'],'ssh':['-V'],'ldd':['--version'],'gcc':['--version'],'ld':['--version'],'as':['--version']}.items():
  p=shutil.which(name);tools[name]={'path':p,'binary_sha256':sha(Path(p).resolve()) if p else None,'version':command([p,*args]) if p else None}
 result={'schema':1,'kind':'ci-v3-runtime-fingerprint','python':sys.version,'python_executable':str(Path(sys.executable).resolve()),'python_binary_sha256':sha(Path(sys.executable).resolve()),
  'os_release':Path('/etc/os-release').read_text() if Path('/etc/os-release').exists() else None,'kernel':platform.release(),'libc':platform.libc_ver(),'machine':platform.machine(),
  'cpu':cpu,'cpu_count':os.cpu_count(),'affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,'cgroup_limits':limits,
  'native_thread_environment':{n:os.environ.get(n) for n in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']},
  'pytest_plugin_autoload':os.environ.get('PYTEST_DISABLE_PLUGIN_AUTOLOAD'),
  'packages':sorted(packages,key=lambda p:(p['name'] or '',p['version'])),'native_shared_libraries_sha256':dict(sorted(native.items())),'runtime_tools':tools,
  'authority':'observation only; no source/service provenance or equivalence approval'}
 return result

def capture():
 result = dict(_static_capture())
 result["native_thread_environment"] = {n: os.environ.get(n) for n in ["OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS","NUMEXPR_NUM_THREADS"]}
 result["pytest_plugin_autoload"] = os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
 return result
