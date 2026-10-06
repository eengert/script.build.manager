"""Creation-free, lock-free, bounded reads of Build Manager state files.

Build Manager writers replace durable state atomically (staged file plus
``os.replace``), so a reader that takes no lock always sees one complete,
consistent record. Status reads use this helper instead of the stores'
locking ``inspect()`` methods, which create the profile directory and lock
file and would fail while another operation holds the lock.
"""

from __future__ import annotations

import errno
import os
import stat
from typing import Optional


class ReadOnlyStateError(OSError):
    """The state file exists but could not be read (permissions, I/O)."""


class UnsafeStateFile(ReadOnlyStateError):
    """The state file is not a safe regular file: a symlink, FIFO, directory, or oversized.

    Distinct from a plain I/O failure because Build Manager never writes state
    that way, so it is invalid state rather than an unreadable record.
    """


def read_regular_file(path: str, *, limit: int, dir_fd: Optional[int] = None) -> Optional[bytes]:
    """Return the file's bytes, or ``None`` when it does not exist.

    Never creates, truncates, locks, or follows a symlink, and never blocks on
    a FIFO or device (opened non-blocking, then required to be a regular file).
    """
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise UnsafeStateFile("state file is a symbolic link") from exc
        raise ReadOnlyStateError("state file could not be opened") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeStateFile("state file is not a regular file")
        if info.st_size > limit:
            raise UnsafeStateFile("state file is too large")
        chunks = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except ReadOnlyStateError:
        raise
    except OSError as exc:
        raise ReadOnlyStateError("state file could not be read") from exc
    finally:
        os.close(fd)
    if len(data) > limit:
        raise UnsafeStateFile("state file is too large")
    return data
