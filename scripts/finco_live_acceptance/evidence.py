"""Fixed-schema private artifacts; never serialize browser request/response bodies."""
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

STATUSES={'PASS','FAIL','BLOCKED_AUTH','BLOCKED_NO_SYNTHETIC_PROJECT','NOT_SUPPORTED','NOT_TESTED'}
FIELDS=('id','technology','viewport','route','source_contract','url_template','status','reason','screenshot_viewport','screenshot_full','evidence_status','page_width','viewport_width','overflow','clipped_controls','essential_visible','keyboard_focusable','console_errors','page_errors','api_failures','mutation_attempts','unlabelled_controls','misaligned_labels','inner_scroll_regions','navigation_reachability','notes_toggle')


def write_json(path: Path, value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')


def write_csv(path: Path, rows, fields=None):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or tuple(rows[0]) if rows else fields or ('status','reason'),extrasaction='raise')
        w.writeheader();w.writerows(rows)


def references(paths):
    """Read finding IDs/statuses only. Nested packets are data, never commands."""
    refs={};catalog=[];seen=set();budget=[64*1024*1024]
    def scan(raw,label,depth=0):
        if depth>2 or len(raw)>32*1024*1024:return
        sha=hashlib.sha256(raw).hexdigest()
        if sha in seen:return
        seen.add(sha);catalog.append({'source':label,'sha256':sha,'availability':'AVAILABLE'})
        try:z=zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:raise ValueError('REFERENCE_ZIP_MALFORMED') from None
        with z:
            if len(z.infolist())>2000:raise ValueError('REFERENCE_ARCHIVE_LIMIT')
            for f in z.infolist():
                if f.file_size>32*1024*1024:continue
                if f.filename.endswith(('.csv','.zip')):
                    budget[0]-=f.file_size
                    if budget[0]<0:raise ValueError('REFERENCE_ARCHIVE_LIMIT')
                if f.filename.endswith('.zip') and 'SOURCE_EVIDENCE/' in f.filename:scan(z.read(f),Path(f.filename).name,depth+1)
                if f.filename.lower().endswith('.csv') and ('finding' in f.filename.lower() or 'delta' in f.filename.lower()):
                    for number,row in enumerate(csv.DictReader(io.StringIO(z.read(f).decode('utf-8-sig')))):
                        if number>10000:raise ValueError('REFERENCE_CSV_LIMIT')
                        key=next((str(v).strip() for k,v in row.items() if k and k.lower() in ('id','finding_id','item')),None)
                        if key not in {f'L{i:02}' for i in range(1,11)}:continue
                        status=next((str(v).strip() for k,v in row.items() if k and k.lower() in ('status','result','verdict')),'UNKNOWN')
                        refs.setdefault(key,[])
                        if len(refs[key])>=10:continue
                        refs[key].append({'reference':sha+':'+Path(f.filename).name+'#'+key,'status':status if status in {'PASS','FAIL','FIXED','STILL_FAIL','PARTIAL','NOT_TESTED','NOT_IMPLEMENTED','EXPECTED_UNSUPPORTED'} else 'UNKNOWN'})
    for p in paths:
        if not p.is_file():catalog.append({'source':p.name,'availability':'INPUT_NOT_AVAILABLE'});continue
        scan(p.read_bytes(),p.name)
    return refs,catalog


def validate(directory):
    root=Path(directory);errors=[]
    try:
        with (root/'ROUTE_VIEWPORT_MATRIX.csv').open() as f:rows=list(csv.DictReader(f))
        if not rows:errors.append('EMPTY_COVERAGE')
        ids=set()
        for row in rows:
            if set(row)!=set(FIELDS) or row['id'] in ids or row['status'] not in STATUSES:errors.append('INVALID_ROW_SCHEMA')
            ids.add(row['id'])
            for key in ('screenshot_viewport','screenshot_full'):
                p=root/row[key]
                if not row[key] or root.resolve() not in p.resolve().parents or not p.is_file() or p.stat().st_size==0:
                    errors.append('NOT_CAPTURED:'+row['id'])
        for n in ('RELEASE_PROVENANCE.json','TEST_REPORT.json'):
            if not isinstance(json.loads((root/n).read_text()),dict):errors.append('INVALID_JSON_SCHEMA')
    except (OSError,ValueError,KeyError,TypeError):errors.append('MALFORMED_EVIDENCE')
    return sorted(set(errors))


def seal(root):
    entries=[]
    for p in sorted(root.rglob('*')):
        if p.is_symlink():raise ValueError('EVIDENCE_SYMLINK_REFUSED')
        if p.is_file() and p.name!='MANIFEST_SHA256.txt':entries.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix())
    (root/'MANIFEST_SHA256.txt').write_text('\n'.join(entries)+'\n')
