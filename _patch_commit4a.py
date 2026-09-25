import io

# ── project_library_service.py: canonical + cloneable sets, definitions ─────
p = 'app/services/project_library_service.py'
s = io.open(p, encoding='utf-8').read()

old = '''CANONICAL_REFERENCE_TEMPLATE_SOURCES = frozenset({
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_storage_reference",
})'''
new = '''CANONICAL_REFERENCE_TEMPLATE_SOURCES = frozenset({
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_storage_reference",
    "generic_ev_charging_reference",
})'''
assert old in s, "canonical set"
s = s.replace(old, new)

old = '''CLONEABLE_TEMPLATE_SOURCES = frozenset({"generic_wind_reference", "generic_solar_reference"})'''
new = '''CLONEABLE_TEMPLATE_SOURCES = frozenset({
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_ev_charging_reference",
})'''
assert old in s, "cloneable set"
s = s.replace(old, new)

old = '''    {
        "template_source": "generic_storage_reference",
        "project_type": "Storage",
        "display_name": "Generic Storage Reference",
        "project_code": "generic_storage_reference-reference",
        "factory": "create_generic_storage_reference",
    },
]'''
new = '''    {
        "template_source": "generic_storage_reference",
        "project_type": "Storage",
        "display_name": "Generic Storage Reference",
        "project_code": "generic_storage_reference-reference",
        "factory": "create_generic_storage_reference",
    },
    {
        "template_source": "generic_ev_charging_reference",
        "project_type": "EV Charging",
        "display_name": "Generic EV Charging Hub Reference",
        "project_code": "generic_ev_charging_reference-reference",
        "factory": "create_generic_ev_charging_reference",
    },
]'''
assert old in s, "definitions"
s = s.replace(old, new)

old = '''        ts in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference") or spt in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference")'''
new = '''        ts in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_ev_charging_reference") or spt in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_ev_charging_reference")'''
assert old in s, "protected check"
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('project_library_service ok')

# ── protected_reference_service.py ──────────────────────────────────────────
p = 'app/ui/protected_reference_service.py'
s = io.open(p, encoding='utf-8').read()
old = '''PROTECTED_REFERENCE_TEMPLATE_SOURCES: frozenset[str] = frozenset({
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_storage_reference",
})'''
new = '''PROTECTED_REFERENCE_TEMPLATE_SOURCES: frozenset[str] = frozenset({
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_storage_reference",
    "generic_ev_charging_reference",
})'''
assert old in s, "protected service"
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('protected_reference_service ok')

# ── export_metadata.py ──────────────────────────────────────────────────────
p = 'app/export_metadata.py'
s = io.open(p, encoding='utf-8').read()
old = '''REFERENCE_PROJECT_KEYS = {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference"}'''
new = '''REFERENCE_PROJECT_KEYS = {
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_storage_reference",
    "generic_ev_charging_reference",
}'''
assert old in s, "export metadata"
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('export_metadata ok')

# ── scenario_state_service.py ───────────────────────────────────────────────
p = 'app/services/scenario_state_service.py'
s = io.open(p, encoding='utf-8').read()
old = '''    if source in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_wind", "generic_solar", "generic_storage"}:'''
if old not in s:
    import re
    m = re.search(r'source in \{[^}]*generic_storage[^}]*\}', s)
    print('scenario_state pattern:', m.group(0) if m else 'NOT FOUND')
else:
    new = old.replace("generic_storage_reference", "generic_storage_reference, generic_ev_charging_reference", 1)
    new = new.replace('"generic_storage"', '"generic_storage", "generic_ev_charging"', 1)
    s = s.replace(old, new)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('scenario_state ok')

# ── inputs_summary.py ───────────────────────────────────────────────────────
p = 'app/ui/inputs_summary.py'
s = io.open(p, encoding='utf-8').read()
old = '''        (project_record.template_source or "").strip().lower() in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference")'''
assert old in s, "inputs summary"
new = old.replace("generic_storage_reference)", "generic_storage_reference, generic_ev_charging_reference)")
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('inputs_summary ok')

# ── library/router.py order map ─────────────────────────────────────────────
p = 'app/library/router.py'
s = io.open(p, encoding='utf-8').read()
old = '''    order = {"generic_solar_reference": 0, "generic_wind_reference": 1, "generic_storage_reference": 2}'''
new = '''    order = {
        "generic_solar_reference": 0,
        "generic_wind_reference": 1,
        "generic_storage_reference": 2,
        "generic_ev_charging_reference": 3,
    }'''
assert old in s, "library order"
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('library router ok')

# ── projects_create_service.py normalized sets ──────────────────────────────
p = 'app/services/projects_create_service.py'
s = io.open(p, encoding='utf-8').read()
count = s.count('"generic_wind_reference", "generic_solar_reference", "generic_storage_reference"')
print('projects_create_service occurrences:', count)
s = s.replace(
    '"generic_wind_reference", "generic_solar_reference", "generic_storage_reference"',
    '"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_ev_charging_reference"',
)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('projects_create_service ok')

# ── inputs_summary normalize duplicate (already done above) ─────────────────
print('done')
