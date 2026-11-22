#!/usr/bin/env python3
"""Restore the VPS split backup into a new private drill directory."""
import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import tempfile


class DrillError(Exception):
    pass

PRODUCTION = Path("/var/www/universal-web")
STAGING = Path("/opt/universal-web/staging/carlosbarcelo-051")
TABLES = ("sites", "site_domains", "pages", "posts", "media", "users")


def check(condition, message):
    if not condition:
        raise DrillError(message)


def extract_media(archive, destination, prefix):
    with tarfile.open(archive, "r:gz") as source:
        for item in source:
            path = PurePosixPath(item.name)
            check(not path.is_absolute() and ".." not in path.parts, "Unsafe archive path")
            check(item.isdir() or item.isreg(), "Unsupported archive member type")
            if item.isdir() and path in prefix.parents:
                continue
            check(path.is_relative_to(prefix), "Media archive prefix does not match")
            target = destination.joinpath(*path.relative_to(prefix).parts)
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(item) as contents, target.open("xb") as output:
                    shutil.copyfileobj(contents, output)


def inspect(database, media):
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        check(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "SQLite integrity failed")
        check(db.execute("PRAGMA foreign_key_check").fetchone() is None, "SQLite foreign key check failed")
        schema = int(db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0])
        counts = tuple(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES)
        check(db.execute("SELECT 1 FROM sites WHERE slug = ? AND theme = ?",
                         ("carlos-barcelo-serrabona", "carlosbarcelo")).fetchone(),
              "Expected site or theme assignment missing")
        for (reference,) in db.execute("SELECT path FROM media"):
            target = (media / reference).resolve()
            check(target.is_relative_to(media) and target.is_file(), "Media reference missing or unsafe")
        return schema, counts


def migrate_copy(data, release):
    subprocess.run(["/usr/bin/php", "-d", "display_errors=0", "-d", "log_errors=0", "-r",
                    'define("UW_DATA", $argv[1]); require $argv[2]; '
                    'if (UW_VERSION !== "0.5.1" || UW_SCHEMA !== 15) exit(2); ensure_schema();',
                    str(data), str(release.resolve(strict=True) / "app/core.php")],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Directory containing the three restored objects")
    parser.add_argument("workspace", type=Path, help="Existing private working directory for the drill")
    parser.add_argument("--media-prefix", required=True, type=PurePosixPath,
                        help="Archive root for media, use . for media files at archive root")
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--theme", required=True, type=Path, help="Trusted copy of the custom theme")
    args = parser.parse_args()
    parent = args.workspace.resolve(strict=True)
    check(not any(parent.is_relative_to(p) for p in (PRODUCTION, STAGING, args.release.resolve())),
          "Workspace overlaps production, staging or release")
    check(parent.stat().st_uid == os.geteuid() and not (parent.stat().st_mode & 0o077),
          "Workspace must be private and owned by the executing user")
    check(os.geteuid() != 0, "Run the drill as an unprivileged user")
    check(not args.media_prefix.is_absolute() and ".." not in args.media_prefix.parts,
          "Invalid media prefix")
    backup = args.backup.resolve(strict=True)
    for name in ("universal.sqlite", "config.php", "media.tar.gz"):
        check(stat.S_ISREG((backup / name).lstat().st_mode) and (backup / name).stat().st_size > 0,
              "Missing or invalid backup object")
    check(not any((backup / ("universal.sqlite" + suffix)).exists()
                  for suffix in ("-wal", "-shm", "-journal")), "Backup is not a standalone SQLite snapshot")
    theme = args.theme.resolve(strict=True)
    check((theme / "layout.php").is_file() and (theme / "theme.json").is_file(),
          "Custom theme is incomplete")
    check(not any(path.is_symlink() for path in theme.rglob("*")), "Symlink in custom theme")
    with tempfile.TemporaryDirectory(prefix="drill-", dir=parent) as path:
        root = Path(path)
        media = root / "media"
        media.mkdir()
        database = root / "universal.sqlite"
        shutil.copyfile(backup / "universal.sqlite", database)
        extract_media(backup / "media.tar.gz", media, args.media_prefix)
        source_schema, before = inspect(database, media)
        check(source_schema <= 15, "Backup schema is newer than the release")
        migrate_copy(root, args.release)
        schema, after = inspect(database, media)
        check(schema == 15 and after == before, "Schema or protected table counts changed unexpectedly")
    print(f"restore=OK source_schema={source_schema} target_schema={schema} sqlite=OK media=OK theme=OK")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except DrillError as error:
        raise SystemExit(f"restore=FAIL: {error}") from None
    except (OSError, sqlite3.Error, subprocess.SubprocessError, tarfile.TarError, TypeError, IndexError):
        raise SystemExit("restore=FAIL (check inputs, archive layout, SQLite and PHP CLI)") from None
