"""Raw registrations retained, semantic identities deterministic without losing extras."""
from tools.ci_v3_pytest_config import semantic_plugin_profile


def test_object_addresses_normalize_without_dropping_duplicate_or_ambient_plugins():
    a={'registration':'123','module':'tools.ci_v3_pytest_adapter','implementation':'Adapter','file_sha256':None}
    b={**a,'registration':'456'}
    assert semantic_plugin_profile([a])==semantic_plugin_profile([b])
    extra={'registration':'extra','module':'ambient.plugin','implementation':'module','file_sha256':'a'*64}
    assert len(semantic_plugin_profile([a,b,extra]))==3
    assert semantic_plugin_profile([a,extra])!=semantic_plugin_profile([a])
    assert a['registration']=='123'
