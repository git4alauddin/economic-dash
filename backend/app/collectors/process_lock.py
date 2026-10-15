"""Nonblocking kernel locks; process exit releases ownership without stale PID files."""

import errno
import os
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class ProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self._file = None

    def acquire(self) -> bool:
        if self._file is not None:
            raise RuntimeError("This lock is already held.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise
        self._file = handle
        return True

    def release(self) -> None:
        if self._file is None:
            return
        handle, self._file = self._file, None
        try:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
        # Never unlink a lock file: another process may already hold its inode.
