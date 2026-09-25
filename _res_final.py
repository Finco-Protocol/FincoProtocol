import io, re

def sub(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) >= count, (path, old[:70])
    s = s.replace(old, new, count)
    assert '<<<<<<<' not in s and '>>>>>>>' not in s, path
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('fixed', path)

print('saas already resolved')
s = io.open('app/ui/inputs_slice1.py', encoding='utf-8').read()
m = re.search(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> [^\n]*\n', s, re.S)
assert m
merged = m.group(1) + '\n' + m.group(2)
s = s[:m.start()] + merged + s[m.end():]
assert '<<<<<<<' not in s
io.open('app/ui/inputs_slice1.py', 'w', encoding='utf-8', newline='\n').write(s)
print('fixed app/ui/inputs_slice1.py')

sub('tests/test_api_v1_model_references.py',
'''<<<<<<< HEAD
def test_a3_04_list_count_3(client):
=======
def test_a3_04_list_count(client):
    # Solar + Wind + EV Charging (V1) — the canonical reference set.
>>>>>>> a1613ed (EV Charging V1 (4/5): canonical reference registry integration)''',
'''def test_a3_04_list_count_4(client):
    # Solar + Wind + Data Center + EV Charging — the canonical reference set.''')
s = io.open('tests/test_api_v1_model_references.py', encoding='utf-8').read()
assert 'assert _list(client).json()["data"]["count"] == 3' in s
s = s.replace('assert _list(client).json()["data"]["count"] == 3',
              'assert _list(client).json()["data"]["count"] == 4')
io.open('tests/test_api_v1_model_references.py', 'w', encoding='utf-8', newline='\n').write(s)
print('count updated test_api_v1_model_references.py')

sub('tests/test_reference_seed_service.py',
'''<<<<<<< HEAD
    with pytest.raises(ValueError, match="Solar, Wind and Data Center only"):
=======
    with pytest.raises(ValueError, match="Solar, Wind and EV Charging only"):
>>>>>>> a1613ed (EV Charging V1 (4/5): canonical reference registry integration)''',
'''    with pytest.raises(ValueError, match="Solar, Wind, Data Center and EV Charging only"):''')

for path in ('app/input_adapter.py', 'app/services/reference_seed_service.py'):
    s = io.open(path, encoding='utf-8').read()
    s = re.sub(r'^>>>>>>> [^\n]*\n', '', s, flags=re.M)
    assert '<<<<<<<' not in s and '>>>>>>>' not in s, path
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('fixed', path)
