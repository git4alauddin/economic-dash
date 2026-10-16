"""One SQLite driver for connections, rows and exception handling.

Render's system SQLite can reject JSON CHECK constraints with trusted_schema=OFF.
The pinned Linux wheel bundles SQLite independently of the host system library.
Other platforms use Python's SQLite. Never replace process-global modules.
"""

import platform
import sys

if sys.platform == "linux" and platform.machine() == "x86_64":
    import pysqlite3 as sqlite3
else:
    import sqlite3
