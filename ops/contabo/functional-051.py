#!/usr/bin/env python3
"""Run the HTTP drill inside a loopback-only network namespace."""
import argparse
import base64
import errno
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlencode, urlsplit

from restore_051 import DrillError, PRODUCTION, STAGING, check, extract_media, inspect

PHP = "/usr/bin/php"
HOST = "127.0.0.1"
EMAIL = "uw-functional@example.invalid"
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEElEQVR4nGNgaL6EHQ0tCQAbN1VB9JIUfwAAAABJRU5ErkJggg=='
)
STAGE = "preflight"


def isolated():
    host_namespace = os.environ.get("UW_DRILL_HOST_NETNS", "")
    check(re.fullmatch(r"net:\[\d+\]", host_namespace), "Host network namespace reference missing")
    check(os.readlink("/proc/self/ns/net") != host_namespace, "Network namespace matches host reference")
    interfaces = Path("/proc/net/dev").read_text().splitlines()[2:]
    check({line.split(":", 1)[0].strip() for line in interfaces} == {"lo"},
          "Namespace has a non-loopback interface")
    # UDP connect selects a route without sending a packet.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 443))
        except OSError as error:
            check(error.errno == errno.ENETUNREACH, "Unexpected IPv4 routing probe result")
        else:
            raise DrillError("External IPv4 route exists")


def fingerprint(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def copy_tree(source, destination, ignored=()):
    check(source.is_dir() and source.resolve() == source, "Invalid source directory")
    for name in source.iterdir():
        if name.name in ignored:
            continue
        mode = name.lstat().st_mode
        check(stat.S_ISREG(mode) or stat.S_ISDIR(mode), "Source has a link or special file")
        target = destination / name.name
        if stat.S_ISDIR(mode):
            target.mkdir(exist_ok=True)
            copy_tree(name, target)
        else:
            shutil.copyfile(name, target)


def snapshot_database(source, target):
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            check(dst.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",),
                  "Candidate journal mode could not be normalized")


def complete_schema_15(database):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("BEGIN")
        for table in ("pages", "posts"):
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if "path" not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN path TEXT NOT NULL DEFAULT ''")
            if "content_at" not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN content_at TEXT")
                db.execute(f"UPDATE {table} SET content_at = updated_at WHERE content_at IS NULL")
            db.execute(f"CREATE INDEX IF NOT EXISTS {table}_path ON {table} (site_id, path)")


def sanitize(database, data, password):
    hashed = subprocess.run([PHP, "-r", "echo password_hash(stream_get_contents(STDIN), PASSWORD_DEFAULT);"],
                            input=password, text=True, capture_output=True, check=True).stdout
    check(hashed.startswith("$"), "Could not generate test password hash")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        site = db.execute("SELECT id FROM sites WHERE slug=?", ("carlos-barcelo-serrabona",)).fetchone()[0]
        db.execute("DELETE FROM site_domains")
        db.execute("INSERT INTO site_domains(domain,site_id,is_primary) VALUES (?,?,1)", (HOST, site))
        # Retain user IDs to preserve references. Make all imported credentials unusable.
        db.execute("UPDATE users SET password_hash='', totp_secret='', totp_last_step=0, recovery_codes='[]'")
        for table in ("tokens", "password_resets", "site_forms", "site_publish", "backup_offsite", "throttle"):
            db.execute(f"DELETE FROM {table}")
        db.execute("DELETE FROM meta WHERE key='platform'")
        settings = json.loads(db.execute("SELECT settings FROM sites WHERE id=?", (site,)).fetchone()[0])
        settings["indexnow"] = False
        settings.pop("private", None)
        db.execute("UPDATE sites SET settings=? WHERE id=?", (json.dumps(settings), site))
        user = db.execute(
            "INSERT INTO users(email,name,password_hash,created_at) VALUES (?,?,?,datetime('now'))",
            (EMAIL, "Functional drill", hashed)).lastrowid
        db.execute("INSERT INTO site_users(site_id,user_id,role) VALUES (?,?,?)", (site, user, "admin"))
        check(db.execute("PRAGMA foreign_key_check").fetchone() is None, "Sanitized DB references failed")
    (data / "config.php").write_text(
        "<?php return ['secret'=>'" + secrets.token_hex(32) + "', 'timezone'=>'Europe/Madrid', "
        f"'default_site_id'=>{site}, 'debug'=>false, 'version'=>'0.5.1'];\n")
    return site


class TokenParser(HTMLParser):
    value = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "_csrf":
            self.value = attrs.get("value")


class Client:
    def __init__(self, port):
        self.port = port
        self.cookies = {}

    def request(self, path, expected, fields=None, raw=None, content_type=None):
        headers = {"Host": f"{HOST}:{self.port}", "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        if fields is not None:
            raw = urlencode(fields).encode()
            content_type = "application/x-www-form-urlencoded"
        if raw is not None:
            headers["Content-Type"] = content_type
            headers["Origin"] = f"http://{HOST}:{self.port}"
        conn = http.client.HTTPConnection(HOST, self.port, timeout=10)
        try:
            conn.request("GET" if raw is None else "POST", path, raw, headers)
            response = conn.getresponse()
            for key, value in response.getheaders():
                if key.lower() == "set-cookie":
                    name, cookie = value.split(";", 1)[0].split("=", 1)
                    self.cookies[name] = cookie
            check(response.status in expected, f"Unexpected HTTP status {response.status}")
            return response.read(), response.getheader("Location", "")
        finally:
            conn.close()

    def csrf(self, path):
        parser = TokenParser()
        parser.feed(self.request(path, (200,))[0].decode("utf-8"))
        check(parser.value, "No CSRF field in test form")
        return parser.value


def verify_http(client, app, db, site, password, slug, theme_probe):
    global STAGE
    redirects = (302, 303)
    STAGE = "http_theme"
    body, _ = client.request("/", (200,))
    check(body and theme_probe.is_file(), "Homepage did not execute the custom layout")
    STAGE = "authentication"
    login = "/admin/login"
    _, loc = client.request("/admin/", redirects)
    check(urlsplit(loc).path == login, "Anonymous admin request was not redirected to login")
    for secret in ("invalid-" + password, password):
        _, loc = client.request(login, redirects, {"_csrf": client.csrf(login), "email": EMAIL, "password": secret})
        want = login if secret != password else "/admin/"
        check(urlsplit(loc).path == want, "Unexpected login outcome")
    STAGE = "admin_read"
    client.request("/admin/", (200,))
    client.request("/admin/pages", (200,))
    client.request("/admin/posts", (200,))
    STAGE = "content_write"
    fields = {"_csrf": client.csrf("/admin/pages/edit"), "slug": slug,
              "title": "Functional drill " + slug, "status": "draft", "blocks": "[]"}
    _, loc = client.request("/admin/pages/save", redirects, fields)
    match = re.fullmatch(r"/admin/pages/edit\?id=(\d+)", loc)
    check(match, "Draft creation did not return its ID")
    fields.update(id=match[1], title="Functional edited " + slug, status="published", path="/" + slug)
    client.request(loc, (200,))
    client.request("/admin/pages/save", redirects, fields)
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT title,status FROM pages WHERE site_id=? AND slug=?", (site, slug)).fetchone()
        check(row == (fields["title"], "published"), "Edited content not persisted")
    body, _ = client.request("/" + slug, (200,))
    check(fields["title"].encode() in body, "Published test page did not render")
    STAGE = "media_upload"
    boundary = "uw-" + secrets.token_hex(16)
    csrf = client.csrf("/admin/media")
    raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="_csrf"\r\n\r\n{csrf}\r\n'
           f'--{boundary}\r\nContent-Disposition: form-data; name="files[]"; filename="{slug}.png"\r\n'
           "Content-Type: image/png\r\n\r\n").encode() + PNG + f"\r\n--{boundary}--\r\n".encode()
    client.request("/admin/media/upload", redirects, raw=raw, content_type=f"multipart/form-data; boundary={boundary}")
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT path FROM media WHERE site_id=? AND original_name=?",
                                 (site, slug + ".png")).fetchone()
    check(row, "Uploaded file not recorded")
    payload, _ = client.request("/media/" + row[0], (200,))
    check(payload == (app / "public/media" / row[0]).read_bytes() and payload, "Served media differs")
    STAGE = "logout"
    client.request("/admin/logout", redirects, {"_csrf": client.csrf("/admin/")})
    _, loc = client.request("/admin/pages", redirects)
    check(urlsplit(loc).path == login, "Logged-out session still has panel access")


def main():
    global STAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    check(os.geteuid() != 0, "Run as the unprivileged operator")
    isolated()
    backup, workspace = args.backup.resolve(strict=True), args.workspace.resolve(strict=True)
    release = Path("/opt/universal-web/releases/0.5.1")
    theme = STAGING / "themes/carlosbarcelo"
    check(not any(workspace.is_relative_to(p) for p in (PRODUCTION, STAGING, release, backup)),
          "Workspace overlaps a protected tree")
    check(workspace.stat().st_uid == os.geteuid() and not workspace.stat().st_mode & 0o077,
          "Workspace must be owned by the operator and private")
    db_source, media_source = backup / "universal.sqlite", backup / "media.tar.gz"
    for path in (db_source, media_source):
        check(path.is_file() and not path.is_symlink(), "Invalid backup input")
    check(not any(backup.is_relative_to(path) for path in (PRODUCTION, STAGING, release)),
          "Backup input is under a protected tree")
    before = tuple(fingerprint(path) for path in (db_source, media_source, theme / "layout.php"))
    with tempfile.TemporaryDirectory(prefix="http-drill-", dir=workspace) as tmp:
        root = Path(tmp)
        app, data, sessions = (root / name for name in ("app", "data", "sessions"))
        for path in (app, data, sessions):
            path.mkdir()
        STAGE = "prepare"
        copy_tree(release, app, {"data", ".git"})
        media = app / "public/media"
        if media.exists():
            shutil.rmtree(media)
        media.mkdir()
        extract_media(media_source, media, PurePosixPath("media"))
        custom = app / "themes/carlosbarcelo"
        if custom.exists():
            shutil.rmtree(custom)
        custom.mkdir()
        copy_tree(theme, custom)
        db = data / "universal.sqlite"
        snapshot_database(db_source, db)
        check(inspect(db, media)[0] == 15, "Functional drill needs an already-verified schema 15 backup")
        core = (app / "app/core.php").read_text()
        check(re.search(r"""const UW_VERSION = ['"]0\.5\.1['"];""", core), "Incorrect release version")
        password, slug = secrets.token_urlsafe(24), "uw-drill-" + secrets.token_hex(6)
        complete_schema_15(db)
        site = sanitize(db, data, password)
        # Confirm the custom renderer ran, without modifying the source theme or logging its HTML.
        layout, probe = custom / "layout.php", root / "theme-rendered"
        layout.rename(custom / "layout-drill-original.php")
        layout.write_text("<?php file_put_contents(" + json.dumps(str(probe)) +
                          ", 'ok'); require __DIR__ . '/layout-drill-original.php';")
        STAGE = "startup"
        port = 18051  # Private namespace has no other service.
        env = {"PATH": "/usr/bin:/bin", "UW_DATA": str(data), "HOME": str(root), "TMPDIR": str(root)}
        with subprocess.Popen(
            [PHP, "-d", "display_errors=0", "-d", "log_errors=0", "-d", "sendmail_path=/bin/false",
             "-d", "disable_functions=mail,exec,shell_exec,system,passthru,popen,proc_open",
             "-d", "session.save_path=" + str(sessions), "-S", f"{HOST}:{port}",
             "-t", str(app / "public"), str(app / "public/index.php")],
            cwd=app, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ) as server:
            try:
                for _ in range(50):
                    check(server.poll() is None, "PHP HTTP server exited")
                    try:
                        with socket.create_connection((HOST, port), timeout=0.2):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise DrillError("PHP HTTP server did not start")
                verify_http(Client(port), app, db, site, password, slug, probe)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    STAGE = "source_integrity"
    check(before == tuple(fingerprint(path) for path in (db_source, media_source, theme / "layout.php")),
          "Backup or source layout changed during drill")
    print("functional_051=OK isolation=OK http=OK auth=OK admin=OK content=OK media=OK theme=OK")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except Exception as error:
        reason = f": {error}" if isinstance(error, DrillError) else ""
        raise SystemExit(f"functional_051=FAIL stage={STAGE}{reason}") from None
