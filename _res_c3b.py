import io, re

def union(path, resolutions):
    """resolutions: list of (HEAD_block, EV_block, merged_block)."""
    s = io.open(path, encoding='utf-8').read()
    for head_b, ev_b, merged in resolutions:
        conflict = f'<<<<<<< HEAD\n{head_b}\n=======\n{ev_b}\n>>>>>>> '
        # locate the conflict containing these blocks (marker suffix varies)
        m = re.search(re.escape(head_b) + r'\n=======\n' + re.escape(ev_b) + r'\n>>>>>>> [^\n]*\n', s)
        assert m, (path, head_b[:60])
        s = s[:m.start()] + merged + s[m.end():]
    assert '<<<<<<<' not in s, path
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('resolved', path)

# ── project_context.py: DC + EV technology resolution ────────────────────────
union('app/ui/project_context.py', [
    ('''    if resolved_project_type in {"data center", "data_center", "datacenter"}:
        technology = "Data Center"
    else:
        technology = "Solar PV" if resolved_project_type == "solar" else "Wind"''',
     '''    technology = "Solar PV" if resolved_project_type == "solar" else (
        "EV Charging" if resolved_project_type in ("ev charging", "ev_charging") else "Wind"
    )''',
     '''    if resolved_project_type in {"data center", "data_center", "datacenter"}:
        technology = "Data Center"
    elif resolved_project_type in ("ev charging", "ev_charging"):
        technology = "EV Charging"
    else:
        technology = "Solar PV" if resolved_project_type == "solar" else "Wind"'''),
])

# ── validation_status.py: DC + EV validation entries ─────────────────────────
union('app/validation_status.py', [
    ('''    "generic_data_center_reference": ("Generic Data Center Reference", _reference_project_status),
    "generic_data_center": ("Generic Data Center", _generic_project_status),''',
     '''    "generic_ev_charging_reference": ("Generic EV Charging Hub Reference", _reference_project_status),
    "generic_ev_charging": ("Generic EV Charging", _generic_project_status),''',
     '''    "generic_data_center_reference": ("Generic Data Center Reference", _reference_project_status),
    "generic_data_center": ("Generic Data Center", _generic_project_status),
    "generic_ev_charging_reference": ("Generic EV Charging Hub Reference", _reference_project_status),
    "generic_ev_charging": ("Generic EV Charging", _generic_project_status),'''),
])

# ── main_web.py: five additive unions ────────────────────────────────────────
union('main_web.py', [
    ('''    {"value": "generic_data_center_reference", "label": "Generic Data Center Reference", "project_type": "Data Center"},''',
     '''    {"value": "generic_ev_charging_reference", "label": "Generic EV Charging Hub Reference", "project_type": "EV Charging"},''',
     '''    {"value": "generic_data_center_reference", "label": "Generic Data Center Reference", "project_type": "Data Center"},
    {"value": "generic_ev_charging_reference", "label": "Generic EV Charging Hub Reference", "project_type": "EV Charging"},'''),
    ('''    if source in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_wind", "generic_solar", "generic_storage", "generic_data_center"}:
        return source
    if _canonical_project_type(project_type) == "Data Center":
        return "generic_data_center"
    return "generic_solar" if _canonical_project_type(project_type) == "Solar" else ("generic_storage" if _canonical_project_type(project_type) == "Storage" else "generic_wind")''',
     '''    if source in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_ev_charging_reference", "generic_wind", "generic_solar", "generic_storage", "generic_ev_charging"}:
        return source
    canonical = _canonical_project_type(project_type)
    if canonical == "Solar":
        return "generic_solar"
    if canonical == "Storage":
        return "generic_storage"
    if canonical == "EV Charging":
        return "generic_ev_charging"
    return "generic_wind"''',
     '''    if source in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_ev_charging_reference", "generic_wind", "generic_solar", "generic_storage", "generic_data_center", "generic_ev_charging"}:
        return source
    canonical = _canonical_project_type(project_type)
    if canonical == "Solar":
        return "generic_solar"
    if canonical == "Storage":
        return "generic_storage"
    if canonical == "Data Center":
        return "generic_data_center"
    if canonical == "EV Charging":
        return "generic_ev_charging"
    return "generic_wind"'''),
    ('''    if source == "generic_data_center_reference":
        return "generic_data_center_reference", "Generic Data Center Reference"
    if source == "generic_data_center":
        return "generic_data_center", "Generic Data Center Project"''',
     '''    if source == "generic_ev_charging_reference":
        return "generic_ev_charging_reference", "Generic EV Charging Hub Reference"''',
     '''    if source == "generic_data_center_reference":
        return "generic_data_center_reference", "Generic Data Center Reference"
    if source == "generic_data_center":
        return "generic_data_center", "Generic Data Center Project"
    if source == "generic_ev_charging_reference":
        return "generic_ev_charging_reference", "Generic EV Charging Hub Reference"'''),
    ('''            0 if it["project_code"] in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference"} else 1,''',
     '''            0 if it["project_code"] in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_ev_charging_reference"} else 1,''',
     '''            0 if it["project_code"] in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_ev_charging_reference"} else 1,'''),
    ('''    if selection in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_wind", "generic_solar", "generic_storage", "generic_data_center"}:''',
     '''    if selection in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_ev_charging_reference", "generic_wind", "generic_solar", "generic_storage", "generic_ev_charging"}:''',
     '''    if selection in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_ev_charging_reference", "generic_wind", "generic_solar", "generic_storage", "generic_data_center", "generic_ev_charging"}:'''),
])
