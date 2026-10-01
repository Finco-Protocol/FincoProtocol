"""Small durable-write primitive for Yield persistence.

A POSIX ``write(2)`` may consume fewer bytes than supplied.  Persistence paths
(current snapshot temp file, append-only history line) must therefore keep
writing until the whole buffer is on its way to disk and treat zero progress as
a failure -- never as success.  ``fsync`` is the caller's job and must only run
after ``write_all`` returns.
"""
from __future__ import annotations

import os

# Indirection so tests can inject short writes deterministically without
# depending on the filesystem actually producing them.
_write = os.write


class DurableWriteError(OSError):
    """The buffer could not be written in full (fail closed)."""


def write_all(fd: int, data: bytes) -> None:
    """Write every byte of ``data`` to ``fd`` or raise.

    * loops over partial writes;
    * a write that reports no progress raises ``DurableWriteError``;
    * a write that reports more bytes than remained raises (defensive).
    """
    view = memoryview(data)
    total = len(view)
    done = 0
    while done < total:
        written = _write(fd, view[done:])
        if not isinstance(written, int) or written <= 0:
            raise DurableWriteError("write made no progress")
        if written > total - done:
            raise DurableWriteError("write reported more bytes than supplied")
        done += written
