"""Run only via an explicit operator command; no network or browser on import."""
import argparse
from pathlib import Path
import re
import sys
from .policy import Refused


def positive(value):
    number=int(value)
    if number not in (1440,1024,390,320):raise argparse.ArgumentTypeError('Use 1440,1024,390,320')
    return number


class SafeParser(argparse.ArgumentParser):
    def error(self,message):raise Refused('INVALID_CLI_ARGUMENTS')

def parser():
    p=SafeParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');r.add_argument('--base-url',required=True);r.add_argument('--mode',choices=('read-only','synthetic-writable'),default='read-only')
    r.add_argument('--technology',default='solar,wind');r.add_argument('--viewports',default='1440,1024,390,320')
    r.add_argument('--evidence-dir',required=True);r.add_argument('--session-spec');r.add_argument('--allow-synthetic-writes',action='store_true')
    r.add_argument('--reference-zip',action='append',default=[])
    r.add_argument('--expected-js-sha256');r.add_argument('--expected-css-sha256')
    r.add_argument('--route-timeout',type=float,default=15);r.add_argument('--global-timeout',type=float,default=600)
    v=sub.add_parser('validate-evidence');v.add_argument('directory')
    return p


def main(argv=None):
    try:
        args=parser().parse_args(argv)
        if args.command=='validate-evidence':
            from .evidence import validate
            errors=validate(Path(args.directory));print('EVIDENCE_INVALID' if errors else 'EVIDENCE_VALID');return 1 if errors else 0
        args.technology=args.technology.split(',');args.viewports=[positive(v) for v in args.viewports.split(',')]
        if not args.technology or any(t not in ('solar','wind') for t in args.technology) or len(set(args.technology))!=len(args.technology) or len(set(args.viewports))!=len(args.viewports):raise Refused('INVALID_COVERAGE_SELECTION')
        if not 1<=args.route_timeout<=60 or not 5<=args.global_timeout<=3600:raise Refused('INVALID_TIMEOUT')
        for d in (args.expected_js_sha256,args.expected_css_sha256):
            if d is not None and not re.fullmatch('[a-f0-9]{64}',d):raise Refused('INVALID_EXPECTED_DIGEST')
        from .runner import execute
        result=execute(args);print('ON_ACCEPT01_PASS' if result==0 else 'ON_ACCEPT01_FAIL' if result==1 else 'ON_ACCEPT01_BLOCKED');return result
    except Refused as e:print(str(e).split(';',1)[0]);return 64
    except (ValueError,OSError):print('INVALID_CONFIGURATION_OR_PRIVATE_OUTPUT');return 64

def supervised_main(argv):
    """Reuse the existing Linux descendant cleanup; hard wall clock outside Chromium."""
    import json
    import os
    import signal
    import subprocess
    from .policy import target,writable_target
    from .evidence import write_json,seal
    try:
        args=parser().parse_args(argv)
        if args.command!='run':return main(argv)
        target(args.base_url)
        if args.mode=='synthetic-writable':writable_target(args.base_url,args.allow_synthetic_writes)
        if not 5<=args.global_timeout<=3600:raise Refused('INVALID_TIMEOUT')
        out=Path(args.evidence_dir).resolve();checkout=Path(__file__).resolve().parents[2]
        if out.exists() or out==checkout or checkout in out.parents:raise Refused('FRESH_PRIVATE_OUTPUT_REQUIRED')
        from tools.ci_process_cleanup import enable_subreaper,finish_cleanup
        enable_subreaper()
        out.mkdir(mode=0o700,parents=True)
        command=[sys.executable,'-c','from scripts.finco_live_acceptance.__main__ import main; import sys; sys.exit(main(sys.argv[1:]))',*argv]
        child=subprocess.Popen(command,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        reason='NORMAL_EXIT'
        try:code=child.wait(timeout=args.global_timeout+10)
        except (subprocess.TimeoutExpired,KeyboardInterrupt) as exc:
            reason='CANCELLED' if isinstance(exc,KeyboardInterrupt) else 'GLOBAL_WATCHDOG_TIMEOUT';code=130 if reason=='CANCELLED' else 124
            for sig,grace in ((signal.SIGINT,5),(signal.SIGTERM,3),(signal.SIGKILL,3)):
                try:os.killpg(child.pid,sig)
                except ProcessLookupError:break
                try:child.wait(timeout=grace);break
                except subprocess.TimeoutExpired:continue
        cleanup=finish_cleanup()
        # Existing cleanup diagnostics can contain process commands; retain only bounded counts/booleans.
        safe={'reason':reason,'exit_code':code,'cleanup_verified':cleanup['cleanup_verified'],
              'survivors_observed':len(cleanup['survivors_observed']),'survivors_remaining':len(cleanup['survivors_remaining'])}
        if not safe['cleanup_verified']:code=1;safe['exit_code']=code
        write_json(out/'TEARDOWN.json',safe)
        if reason!='NORMAL_EXIT' or not safe['cleanup_verified']:
            try:report=json.loads((out/'TEST_REPORT.json').read_text())
            except (OSError,ValueError):report={'schema':'ON_ACCEPT01_V1'}
            report.update(exit_code=code,verdict='BLOCKED' if code==130 else 'FAIL',stop_reason=reason)
            write_json(out/'TEST_REPORT.json',report)
        seal(out)
        print('ON_ACCEPT01_PASS' if code==0 else 'ON_ACCEPT01_CANCELLED' if code==130 else 'ON_ACCEPT01_TIMEOUT' if code==124 else 'ON_ACCEPT01_FAIL' if code==1 else 'ON_ACCEPT01_BLOCKED')
        return code
    except (Refused,OSError,ValueError,RuntimeError):print('INVALID_OR_UNSAFE_CONFIGURATION');return 64

if __name__=='__main__':sys.exit(supervised_main(sys.argv[1:]))
