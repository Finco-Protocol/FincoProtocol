"""F01 attribution negatives retain source/history failure-catching power."""
import pytest
from tests import finval_f01_scope as F

def test_current_scope_is_exact_and_history_required(tmp_path):
    assert F.valid()
    assert not F.valid(repo=tmp_path)

@pytest.mark.parametrize("path", sorted(F.SOURCES))
def test_every_source_byte_is_enforced(path):
    sources={p:(F.ROOT/p).read_bytes() for p in F.SOURCES}
    sources[path]+=b"\n"
    assert not F.valid(sources=sources)
    del sources[path]
    assert not F.valid(sources=sources)
