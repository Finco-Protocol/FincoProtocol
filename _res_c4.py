import io, re, subprocess

def load(path):
    return io.open(path, encoding='utf-8').read()

def resolve(path, resolutions, required=True):
    s = io.open(path, encoding='utf-8').read()
    for head_b, ev_b, merged in resolutions:
        pat = re.escape(head_b) + r'\n=======\n' + re.escape(ev_b) + r'\n>>>>>>> [^\n]*\n'
        m = re.search(pat, s)
        assert m, (path, head_b[:70])
        s = s[:m.start()] + merged + s[m.end():]
    assert '<<<<<<<' not in s, path
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('resolved', path)

def head_side(path):
    return io.open(path, encoding='utf-8').read()

print('export_metadata already resolved')

# ── projects_repository.py: main's dynamic binding + both entries ────────────
p = 'app/persistence/projects_repository.py'
s = load(p)
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 6
# r0: template tuple — both entries
s = s[:regions[0].start()] + '    "generic_data_center_reference",\n    "generic_ev_charging_reference",' + s[regions[0].end():]
# r1-r3: main's dynamic slots/params
for idx in (1, 2, 3):
    regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
    s = s[:regions[0].start()] + regions[0].group(1) + s[regions[0].end():]
# now only the import + baseline regions remain
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 2, len(regions)
s = s[:regions[0].start()] + '        create_generic_data_center_reference,\n        create_generic_ev_charging_reference,' + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 1
# baseline builder: DC branch (HEAD, verbatim) then EV branch (mine)
dc_b = regions[0].group(1)
ev_b = regions[0].group(2)
merged = dc_b + "\n\n    " + ev_b + "\n"
# fix indentation: ev_b starts with '    if normalized_source...' at same indent
merged = dc_b + "\n\n" + ev_b + "\n"
s = s[:regions[0].start()] + merged + s[regions[0].end():]
assert '<<<<<<<' not in s
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resolved', p)

# ── project_library_service.py: dynamic guard + both entries ─────────────────
p = 'app/services/project_library_service.py'
s = load(p)
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 4
# r0: main's dynamic _generic_reference_keys guard
s = s[:regions[0].start()] + regions[0].group(1) + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 3
s = s[:regions[0].start()] + '    "generic_data_center_reference",\n    "generic_ev_charging_reference",' + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 2
s = s[:regions[0].start()] + '    "generic_data_center_reference",\n    "generic_ev_charging_reference",' + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 1
dc_def, ev_def = regions[0].group(1), regions[0].group(2)
s = s[:regions[0].start()] + dc_def + "\n" + ev_def + s[regions[0].end():]
assert '<<<<<<<' not in s
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resolved', p)

# ── projects_create_service.py: both validations + both seed sets ────────────
p = 'app/services/projects_create_service.py'
s = load(p)
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 2
dc_v, ev_v = regions[0].group(1), regions[0].group(2)
s = s[:regions[0].start()] + dc_v + "\n" + ev_v.replace('\n    ):\n', '\n    ):\n', 1) + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 1
s = s[:regions[0].start()] + '    if normalized_source in {"generic_solar_reference", "generic_wind_reference", "generic_data_center_reference", "generic_ev_charging_reference"}:' + s[regions[0].end():]
assert '<<<<<<<' not in s
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resolved', p)

# ── scenario_state_service.py / protected_reference_service.py: unions ───────
p = 'app/services/scenario_state_service.py'
s = load(p)
m = re.search(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S)
dc, ev = m.group(1), m.group(2)
dc_set = dc.replace('<<<<<<< HEAD\n', '').rstrip()
ev_add = 'generic_ev_charging_reference", "generic_ev_charging'
merged = dc_set.replace('"generic_data_center"}', '"generic_data_center", "generic_ev_charging_reference", "generic_ev_charging"}')
s = s[:m.start()] + merged + '\n' + s[m.end():]
assert '<<<<<<<' not in s
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resolved', p)

p = 'app/ui/protected_reference_service.py'
s = load(p)
m = re.search(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S)
s = s[:m.start()] + m.group(1) + '\n' + m.group(2) + s[m.end():]
assert '<<<<<<<' not in s
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resolved', p)

# ── tests ────────────────────────────────────────────────────────────────────
p = 'tests/test_api_v1_model_references.py'
s = load(p)
m = re.search(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S)
merged = '''def test_a3_04_list_count_4(client):
    # Solar + Wind + Data Center + EV Charging — the canonical reference set.
    assert _list(client).json()["data"]["count"] == 4'''
s = s[:m.start()] + merged + s[m.end():]
assert '<<<<<<<' not in s
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resolved', p)

p = 'tests/test_public_reference_models.py'
s = load(p)
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 5
# r0: imports — both
s = s[:regions[0].start()] + '    create_generic_data_center_reference,\n    create_generic_ev_charging_reference,' + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 4
# r1: refs list — both factories
s = s[:regions[0].start()] + '        create_generic_data_center_reference(),\n        create_generic_ev_charging_reference(),' + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 3
# r2: names + countries
merged = '''        "Generic Data Center Reference",
        "Generic EV Charging Hub Reference",
    ]
    assert [p.info.country_iso for p in refs] == ["XA", "XB", "XC", "XD", "XE"]'''
s = s[:regions[0].start()] + merged + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 2
s = s[:regions[0].start()] + '        "generic_data_center_reference",\n        "generic_ev_charging_reference",' + s[regions[0].end():]
regions = list(re.finditer(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S))
assert len(regions) == 1
s = s[:regions[0].start()] + '        "generic_data_center_reference",\n        "generic_ev_charging_reference",' + s[regions[0].end():]
assert '<<<<<<<' not in s
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resolved', p)

# ── test_saas_revamp_entry.py: take main's structure, count 4 ────────────────
p = 'tests/test_saas_revamp_entry.py'
s = load(p)
m = re.search(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S)
merged = '''    # Solar + Wind + Data Center + EV Charging are cloneable (Storage is not yet).'''
s = s[:m.start()] + merged + s[m.end():]
assert '<<<<<<<' not in s
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resolved', p)
