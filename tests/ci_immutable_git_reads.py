"""Scoped, content-addressed memo for Git object reads named ONLY by full object ids (test infrastructure, never production).

Why: the exact-source governance chain re-reads the same immutable objects (``git show <full-sha>:<path>``) tens of thousands of
times per test through 48 cohort modules (e.g. the unmemoised ``reviewed_edits_ok`` recursion). A Git object id is the hash of the
object's bytes, so such a read has exactly one possible successful answer while the object is present in the store.

Fail-closed rules (each one is an attack test in tests/test_ci_immutable_git_reads.py):
* Only ``subprocess.check_output(["git", ...])`` calls whose EVERY revision is a full 40/64-hex object id and whose form is a pure
  object read (show/rev-parse ``<id>:<path>``, cat-file, ls-tree, ``merge-base --is-ancestor``, two-id ``diff``). Symbolic refs
  (HEAD, branches, ``HEAD~1``), the index (``:path``), the working tree, abbreviated ids and every other form run real git.
* Failures are never memoised; a fresh git error is always re-raised by real git.
* The key binds: the repository's object store (device, inode, real path, alternates) and its config file identity (so a deleted and
  re-created repository at the same path is a different store); a GENERATION stamp of the store (mtimes of ``objects/``, its 256
  fan-out directories, ``pack/`` and every alternate store), so adding, pruning or repacking any object forces a fresh read; the
  global/XDG git config identity; every ``GIT_*`` environment variable; ``PATH``; and the output decoding arguments.
* Replace refs, grafts or a shallow file disable the memo; so do GIT_DIR/GIT_OBJECT_DIRECTORY-style location overrides, ``env=``,
  ``input=`` or any other keyword, a substituted ``subprocess.run``/``Popen``, and calls from any thread other than the one that
  opened the scope.
* Lifetime: one explicit ``scope()`` block (today: the two import-time historical-subject resolutions in tests/test_v9p2a_odr_successor.py and
  tests/test_rc7c_candidate_successor.py; tests/conftest.py is a protected path and is not used). The memo is dropped and ``subprocess.check_output`` restored
  when the outermost scope exits, also on exceptions. A caller that already substituted ``check_output`` keeps its substitute.
* Verdicts are never memoised: every governance function recomputes its decision from the bytes on every call.
"""
from __future__ import annotations

import contextlib
import os
import re
import subprocess
import threading

_HEX = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_REV_PATH = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64}):[^\x00]*$")
_ORIGINAL = subprocess.check_output
_ORIGINAL_RUN = subprocess.run
_ORIGINAL_POPEN = subprocess.Popen
_LOCK = threading.Lock()
_MEMO: dict = {}
_OWNER: list = []          # [thread ident] of the outermost open scope; empty when no scope is open
STATS = {"hits": 0, "misses": 0, "bypass": 0}
_FANOUT = tuple("%02x" % i for i in range(256))

# Environment variables that change which repository, object store, history or object content a call sees: memo disabled.
_RESOLUTION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                   "GIT_INDEX_FILE", "GIT_REPLACE_REF_BASE", "GIT_NO_REPLACE_OBJECTS", "GIT_NAMESPACE", "GIT_SHALLOW_FILE",
                   "GIT_GRAFT_FILE", "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_CONFIG_PARAMETERS")
_ALLOWED_KW = {"cwd", "stderr", "text", "universal_newlines", "encoding", "errors", "timeout"}


def _stat_id(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _git_dir(cwd):
    path = os.path.realpath(cwd if cwd is not None else os.getcwd())
    while True:
        dot = os.path.join(path, ".git")
        if os.path.isdir(dot):
            return dot
        if os.path.isfile(dot):
            with open(dot, encoding="utf-8") as stream:
                line = stream.read().strip()
            if not line.startswith("gitdir: "):
                return None
            gd = line[len("gitdir: "):]
            gd = os.path.realpath(gd if os.path.isabs(gd) else os.path.join(path, gd))
            common = os.path.join(gd, "commondir")
            if os.path.isfile(common):
                with open(common, encoding="utf-8") as stream:
                    c = stream.read().strip()
                gd = os.path.realpath(c if os.path.isabs(c) else os.path.join(gd, c))
            return gd
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def _generation(objects, depth=0):
    """Mtimes of an object store's directories: any added, pruned or repacked object changes at least one of them."""
    stamps = [_stat_id(objects), _stat_id(os.path.join(objects, "pack")), _stat_id(os.path.join(objects, "info"))]
    stamps.extend(_stat_id(os.path.join(objects, d)) for d in _FANOUT)
    alternates = os.path.join(objects, "info", "alternates")
    alt = []
    if os.path.isfile(alternates) and depth < 3:
        with open(alternates, encoding="utf-8") as stream:
            for line in stream.read().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    target = os.path.realpath(line if os.path.isabs(line) else os.path.join(objects, line))
                    alt.append((target, _generation(target, depth + 1)))
    return (tuple(stamps), tuple(alt))


def _store_identity(cwd):
    gd = _git_dir(cwd)
    if gd is None:
        return None
    # History-rewriting mechanisms make an object id name different content/ancestry: never memoise there.
    if os.path.exists(os.path.join(gd, "shallow")) or os.path.exists(os.path.join(gd, "info", "grafts")):
        return None
    replace = os.path.join(gd, "refs", "replace")
    if os.path.isdir(replace) and any(os.scandir(replace)):
        return None
    packed = os.path.join(gd, "packed-refs")
    if os.path.isfile(packed):
        with open(packed, "rb") as stream:
            if b"refs/replace/" in stream.read():
                return None
    objects = os.path.join(gd, "objects")
    home = os.path.expanduser("~")
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    configs = tuple(_stat_id(p) for p in (os.path.join(gd, "config"), os.path.join(home, ".gitconfig"), os.path.join(xdg, "git", "config"),
                                          "/etc/gitconfig"))
    if configs[0] is None:
        return None
    return (os.path.realpath(gd), configs, _generation(objects))


def _eligible(args):
    """True only for pure object reads whose every revision is a full object id."""
    a = list(args)
    if not a:
        return False
    cmd, rest = a[0], a[1:]
    if cmd in ("show", "rev-parse"):
        return len(rest) == 1 and bool(_REV_PATH.match(rest[0]))
    if cmd == "cat-file":
        return len(rest) == 2 and rest[0] in ("-p", "-t", "-s", "blob", "tree", "commit") and bool(_HEX.match(rest[1]) or _REV_PATH.match(rest[1]))
    if cmd == "ls-tree":
        opts, revs, after = [], [], False
        for x in rest:
            if after:
                continue
            if x == "--":
                after = True
            elif x.startswith("-"):
                opts.append(x)
            else:
                revs.append(x)
        return (len(revs) == 1 and bool(_HEX.match(revs[0]))
                and all(o in ("-r", "-t", "-z", "-d", "--name-only", "--full-tree", "--full-name", "-l", "--long") for o in opts))
    if cmd == "merge-base":
        return len(rest) == 3 and rest[0] == "--is-ancestor" and all(_HEX.match(r) for r in rest[1:])
    if cmd == "diff":
        opts, revs, after = [], [], False
        for x in rest:
            if after:
                continue
            if x == "--":
                after = True
            elif x.startswith("-"):
                opts.append(x)
            else:
                revs.append(x)
        return (len(revs) == 2 and all(_HEX.match(r) for r in revs)
                and all(o in ("--name-only", "--name-status", "--raw", "--no-renames", "-z", "--no-ext-diff", "--no-textconv") for o in opts))
    return False


def _split(argv, cwd):
    """('git', ['-C', d,] *args) -> (effective cwd, args) or None."""
    if not isinstance(argv, (list, tuple)) or not argv or argv[0] != "git":
        return None
    a = [os.fspath(x) if isinstance(x, os.PathLike) else x for x in argv[1:]]
    if not all(isinstance(x, str) for x in a):
        return None
    cwd = os.fspath(cwd) if isinstance(cwd, os.PathLike) else cwd
    while a and a[0] == "-C" and len(a) >= 2:
        cwd = a[1] if os.path.isabs(a[1]) or cwd is None else os.path.join(cwd, a[1])
        a = a[2:]
    if a and a[0].startswith("-"):
        return None  # any other global option (-c, --git-dir, --work-tree, ...) is not memoised
    return cwd, a


def check_output(*popenargs, **kwargs):
    argv = popenargs[0] if popenargs else kwargs.get("args")
    split = _split(argv, kwargs.get("cwd")) if len(popenargs) == 1 and "args" not in kwargs else None
    if (split is None or not _eligible(split[1]) or set(kwargs) - _ALLOWED_KW
            or not _OWNER or _OWNER[0] != threading.get_ident()
            or any(k in os.environ for k in _RESOLUTION_ENV)
            # a test that substitutes the process layer (to simulate an unavailable or failing git) always reaches it
            or subprocess.run is not _ORIGINAL_RUN or subprocess.Popen is not _ORIGINAL_POPEN):
        if split is not None:
            STATS["bypass"] += 1
        return _ORIGINAL(*popenargs, **kwargs)
    try:
        store = _store_identity(split[0])
    except (OSError, UnicodeError, ValueError):
        store = None
    if store is None:
        STATS["bypass"] += 1
        return _ORIGINAL(*popenargs, **kwargs)
    env = tuple(sorted((k, v) for k, v in os.environ.items() if k.startswith("GIT_") or k == "PATH"))
    key = (store, env, tuple(split[1]), bool(kwargs.get("text") or kwargs.get("universal_newlines")),
           kwargs.get("encoding"), kwargs.get("errors"))
    with _LOCK:
        if key in _MEMO:
            STATS["hits"] += 1
            return _MEMO[key]
    value = _ORIGINAL(*popenargs, **kwargs)  # raises on failure: never memoised
    with _LOCK:
        if _OWNER:
            _MEMO[key] = value
            STATS["misses"] += 1
    return value


@contextlib.contextmanager
def scope():
    """One read-only block: the memo exists only inside the OUTERMOST block of the opening thread and is dropped on exit (also on exceptions)."""
    if _OWNER:
        yield
        return
    previous = subprocess.check_output
    with _LOCK:
        _OWNER.append(threading.get_ident())
    installed = previous is _ORIGINAL           # a caller's own substitute is never wrapped or bypassed
    if installed:
        subprocess.check_output = check_output
    try:
        yield
    finally:
        if installed and subprocess.check_output is check_output:
            subprocess.check_output = previous
        with _LOCK:
            _MEMO.clear()
            _OWNER.clear()
