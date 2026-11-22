#!/usr/bin/env python3
"""Prepare a private 0.5.1 candidate from a sealed, standalone source tree."""
import argparse
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile

from restore_051 import DrillError, PRODUCTION, STAGING, check, inspect, migrate_copy


def trusted_tree(root):
    check(root.is_dir() and all(stat.S_ISREG(p.lstat().st_mode) or stat.S_ISDIR(p.lstat().st_mode)
                                for p in root.rglob("*")), "Source contains links or special files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Sealed snapshot with data, public/media and theme")
    parser.add_argument("release", type=Path, help="Verified 0.5.1 release tree")
    parser.add_argument("workspace", type=Path, help="Private workspace owned by the operator")
    args = parser.parse_args()
    source, release, workspace = (p.resolve(strict=True) for p in (args.source, args.release, args.workspace))
    check(os.geteuid() != 0, "Run preparation as an unprivileged user")
    check(not source.is_relative_to(PRODUCTION) and not source.is_relative_to(STAGING),
          "Use a sealed copy outside the live and staging trees")
    check(not any(workspace.is_relative_to(p) for p in (PRODUCTION, STAGING, source, release)),
          "Workspace overlaps an input tree")
    check(workspace.stat().st_uid == os.geteuid() and not workspace.stat().st_mode & 0o077,
          "Workspace must be private and owned by the executing user")
    trusted_tree(release)
    check(not (release / "data").exists() and not (release / ".git").exists(),
          "Release must be a clean package without data or Git metadata")
    for name in ("data/universal.sqlite", "data/config.php"):
        p = source / name
        check(p.resolve() == p and p.is_file(), "Missing or linked snapshot file")
    check(not any((source / ("data/universal.sqlite" + suffix)).exists()
                  for suffix in ("-wal", "-shm", "-journal")), "Snapshot contains SQLite sidecars")
    for name in ("themes/carlosbarcelo", "public/media"):
        path = source / name
        check(path.resolve() == path, "Linked snapshot directory")
        trusted_tree(path)
    check(not (release / "themes/carlosbarcelo").exists(), "Release already contains the custom theme")
    candidate = Path(tempfile.mkdtemp(prefix="candidate-051-", dir=workspace))
    try:
        shutil.copytree(release, candidate, dirs_exist_ok=True)
        data = candidate / "data"
        data.mkdir(mode=0o700)
        # Inspect and migrate only the candidate. Keep config out of the migration process.
        shutil.copyfile(source / "data/universal.sqlite", data / "universal.sqlite")
        media = candidate / "public/media"
        shutil.copytree(source / "public/media", media, dirs_exist_ok=True)
        shutil.copytree(source / "themes/carlosbarcelo", candidate / "themes/carlosbarcelo")
        schema, counts = inspect(data / "universal.sqlite", media)
        check(schema <= 15, "Snapshot schema is newer than the release")
        migrate_copy(data, candidate)
        check(inspect(data / "universal.sqlite", media) == (15, counts),
              "Candidate schema, integrity or table counts differ")
        check(not any((data / ("universal.sqlite" + suffix)).exists()
                      for suffix in ("-wal", "-shm", "-journal")), "Candidate has SQLite sidecars")
        shutil.copyfile(source / "data/config.php", data / "config.php")
    except BaseException:
        shutil.rmtree(candidate)
        raise
    print("prepare=OK schema=15")
    print(candidate)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except DrillError as error:
        raise SystemExit(f"prepare=FAIL: {error}") from None
    except (OSError, sqlite3.Error, subprocess.SubprocessError, ValueError, TypeError, IndexError):
        raise SystemExit("prepare=FAIL (check source, release, workspace and PHP CLI)") from None
