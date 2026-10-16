from __future__ import annotations

import errno
import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class LockError(RuntimeError):
    """The global invocation lock could not be acquired."""


@contextmanager
def invocation_lock(directory: Path) -> Iterator[None]:
    """Hold a fail-fast advisory lock; closing the descriptor releases it."""
    path = directory / ".lock"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stream = path.open("a", encoding="utf-8")
    except OSError as exc:
        raise LockError(f"cannot open Tale lock at {path}: {exc}") from exc

    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise LockError("Another Tale invocation is active.") from exc
            raise LockError(f"cannot acquire Tale lock at {path}: {exc}") from exc
        yield
    finally:
        # Keep the file: unlinking it would let contenders lock different inodes.
        # Python opens descriptors as non-inheritable, so commands do not own it.
        stream.close()
