#!/usr/bin/env bash
set -euo pipefail

mode=${1:-}
if [[ $# != 2 || ! $mode =~ ^(deploy|rollback)$ || $2 != --approved || $EUID != 0 ]]; then
    echo "Usage as root after explicit approval: $0 deploy|rollback --approved" >&2
    exit 64
fi

exec 9>/run/lock/universal-web-switch.lock
flock -n 9
# Both roots are siblings so rename exchange is atomic on supported Linux filesystems.
# Before calling, the administrator must stop every writer, including other FPM pools,
# timer/cron tasks and interactive jobs using either tree.
/usr/bin/python3 - "$mode" <<'PY'
import ctypes
import os
from pathlib import Path
import re
import sqlite3
import sys

live = Path("/var/www/universal-web")
slot = Path("/var/www/universal-web-cutover")
deploy = sys.argv[1] == "deploy"

def require(condition, message):
    if not condition:
        raise SystemExit(message)

for directory in (live, slot):
    require(directory.is_dir() and directory.resolve() == directory, "Missing or linked tree")
    require(directory.stat().st_uid == 0 and not directory.stat().st_mode & 0o022,
            "Tree root is writable by non-root or not root-owned")
    require(directory.stat().st_dev == live.parent.stat().st_dev, "Trees must be on one filesystem")
    core = directory / "app/core.php"
    require(core.is_file() and core.resolve() == core, "Missing or linked PHP core")
    data = directory / "data"
    config = data / "config.php"
    db = data / "universal.sqlite"
    require(config.is_file() and config.resolve() == config and not config.stat().st_mode & 0o007,
            "Missing, linked or world-accessible config")
    require(db.is_file() and db.resolve() == db, "Missing or linked SQLite")
    require(not any(db.with_name(db.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")),
            "SQLite sidecars present; stop writers and close/checkpoint SQLite first")
    new = (directory == slot) == deploy
    expected = "0.5.1" if new else "0.3.0"
    version = re.search(r"""const\s+UW_VERSION\s*=\s*['"]([^'"]+)['"]""", core.read_text())
    require(version and version[1] == expected, "Unexpected version in cutover tree")
    if new:
        with sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
            require(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                    "Candidate SQLite integrity check failed")
            require(connection.execute("PRAGMA foreign_key_check").fetchone() is None,
                    "Candidate SQLite foreign key check failed")
            require(connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == ("15",),
                    "Candidate schema must already be 15")

libc = ctypes.CDLL(None, use_errno=True)
exchange = libc.renameat2
exchange.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
if exchange(-100, os.fsencode(live), -100, os.fsencode(slot), 2) != 0:
    # There is deliberately no fallback to two non-atomic renames.
    raise SystemExit("Atomic exchange failed, errno=" + str(ctypes.get_errno()))
print(f"{sys.argv[1]}=OK; review the active tree before reopening writers")
PY
