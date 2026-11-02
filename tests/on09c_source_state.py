"""ON-09C: current authenticated sources include Git mode/type and index.

This module does not grant content authority. Existing exact-blob/lineage gates
still decide approval. Only the immutable accepted manifest closure and existing
protected prefixes are checked; outside staging and untracked CI evidence keep
their existing policy. Explicit Git refs have no working-index requirement.
"""
from __future__ import annotations
import hashlib
import json
import os
import stat
import subprocess
from functools import lru_cache
from pathlib import Path

ACCEPTED = '3e00acab71ea4c2bd9e7396e5bee609225212623'
ACCEPTED_TREE = '12cd2bfb89eac3e628da1bba80efd01b0c47af2f'
MANIFESTS = (
    'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/fin_v2_ci/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json',
    'docs/react_migration/pr394_corrections/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json',
    'docs/react_migration/fin_v2_integration_409/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json',
)
ADDED_MODES = {
    'tests/on09c_source_state.py': '100644',
    'tests/test_on09c_source_state.py': '100644',
    'docs/ci_v3/on09c/SOURCE_STATE.md': '100644',
}
PROTECTED = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')


def _tree(raw):
    rows = {}
    for item in raw.split(b'\0'):
        if not item:
            continue
        meta, name = item.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        rows[os.fsdecode(name)] = (mode, kind, oid)
    return rows


@lru_cache(maxsize=16)
def canonical_modes(root, reader):
    """Immutable Git data only; the injected reader identity is part of the key."""
    if reader(root, 'rev-parse', ACCEPTED + '^{tree}').decode().strip() != ACCEPTED_TREE:
        raise ValueError('accepted tree differs')
    paths = set(MANIFESTS)
    for path in MANIFESTS:
        paths.update(json.loads(reader(root, 'show', ACCEPTED + ':' + path)).get('source_blobs', {}))
    tree = _tree(reader(root, 'ls-tree', '-r', '-z', ACCEPTED))
    modes = {p: row[0] for p, row in tree.items() if p in paths or p.startswith(PROTECTED)}
    modes.update(ADDED_MODES)
    return tuple(sorted(modes.items()))


def _mode(path):
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return 'missing'
    if stat.S_ISREG(mode):
        return '100755' if mode & stat.S_IXUSR else '100644'
    if stat.S_ISLNK(mode):
        return '120000'
    if stat.S_ISDIR(mode):
        return '040000'
    return 'unsupported'


def _working_entry(path):
    """Fresh Git blob bytes and type; never use stat cache as content identity."""
    try:
        before = os.lstat(path)
        mode = _mode(path)
        if mode == '120000':
            data = os.fsencode(os.readlink(path))
        elif mode in ('100644', '100755'):
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, 'rb') as handle:
                opened = os.fstat(handle.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    return ('unstable', None)
                data = handle.read()
                after = os.fstat(handle.fileno())
                current = os.lstat(path)
                observed = '100755' if after.st_mode & stat.S_IXUSR else '100644'
                current_mode = '100755' if current.st_mode & stat.S_IXUSR else '100644'
                if (opened.st_size != len(data) or after.st_size != len(data) or observed != mode
                        or current_mode != mode
                        or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino)
                        or not stat.S_ISREG(current.st_mode)
                        or opened.st_mtime_ns != after.st_mtime_ns
                        or opened.st_ctime_ns != after.st_ctime_ns):
                    return ('unstable', None)
        else:
            return (mode, None)
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        return (mode, blob)
    except OSError:
        return ('unreadable', None)


def _index(raw):
    rows = {}
    for item in raw.split(b'\0'):
        if not item:
            continue
        meta, path = item.split(b'\t', 1)
        tag, mode, oid, stage = meta.decode('ascii').split()
        name = os.fsdecode(path)
        rows.setdefault(name, []).append((tag, mode, oid, stage))
    return rows




def _current_snapshot(root, reader):
    """Authenticate covered index/type/bytes before Git can inspect a FIFO/type change."""
    modes = dict(canonical_modes(str(root), reader))
    raw_index = reader(root, 'ls-files', '--stage', '-v', '-z')
    index = _index(raw_index)
    # A new protected staged entry can disappear from HEAD-to-worktree diff
    # when its working file is removed. It has no approved canonical entry.
    if any(path.startswith(PROTECTED) and path not in modes for path in index):
        return None
    sources = hashlib.sha256()
    for path, mode in sorted(modes.items()):
        entries = index.get(path, [])
        if (len(entries) != 1 or entries[0][0] != 'H' or entries[0][1] != mode
                or entries[0][3] != '0'):
            return None
        observed_mode, observed_blob = _working_entry(Path(root) / path)
        if observed_mode != mode or observed_blob != entries[0][2]:
            return None
        sources.update(os.fsencode(path) + b'\0' + mode.encode() + b'\0' + observed_blob.encode() + b'\0')
    return raw_index, sources.hexdigest()


def state_key(root, ref, reader):
    """Fresh identity, including index-only drift and mode/type even with core.filemode=false.

    No mtime/status-only identity and no positive cache across changed bytes.
    Git binary diff retains existing tracked-byte identity; flags and stages are
    included in the fresh index identity. Unsupported flags on covered sources
    are rejected by authenticated_state_ok, not silently trusted as freshness.
    """
    if ref is not None:
        sha = reader(root, 'rev-parse', ref + '^{commit}').decode().strip()
        return ('ref', str(root), sha)
    snapshot = _current_snapshot(root, reader)
    if snapshot is None:
        return None
    index, sources = snapshot
    head = reader(root, 'rev-parse', 'HEAD').decode().strip()
    tracked = reader(root, 'diff', 'HEAD', '--no-ext-diff', '--binary', '--')
    names = reader(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
    untracked = hashlib.sha256()
    for name in sorted(n for n in names if n):
        try:
            path = Path(root) / os.fsdecode(name)
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(fd, 'rb') as handle:
                # Git enumerates untracked symlinks, including links to pipes.
                # Preserve regular-target links; never wait for a stream writer.
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise OSError('untracked target is not a regular readable file')
                data = handle.read()
        except OSError:
            # Preserve the predecessor's outside-source evidence policy.
            # Covered sources were already read and authenticated above.
            data = b'<unreadable>'
        untracked.update(len(name).to_bytes(8, 'big') + name)
        untracked.update(len(data).to_bytes(8, 'big') + data)
    return ('wt-on09c', str(root), head, hashlib.sha256(tracked).hexdigest(),
            hashlib.sha256(index).hexdigest(), untracked.hexdigest(), sources)


def authenticated_state_ok(root, ref, reader):
    """H-1/H-2. Does not authorize content or ordinary changes outside its finite scope."""
    root = Path(root)
    try:
        modes = dict(canonical_modes(str(root), reader))
        if ref is not None:
            resolved = reader(root, 'rev-parse', ref + '^{commit}').decode().strip()
            if resolved == ACCEPTED:
                modes = {p: m for p, m in modes.items() if p not in ADDED_MODES}
            tree = _tree(reader(root, 'ls-tree', '-r', '-z', ref))
            return all(p in tree and tree[p][0] == mode for p, mode in modes.items())
        return _current_snapshot(root, reader) is not None
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        return False
