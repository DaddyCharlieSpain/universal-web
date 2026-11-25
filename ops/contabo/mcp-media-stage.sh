#!/usr/bin/env bash
set -euo pipefail
umask 077

lab="$HOME/uw-mcp-staging/universal-web-lab.vn9bJ6yw"
repo="$lab/cms"
data="$lab/data"
unit=uw-cms-mcp-staging.service
candidate=be7c6962e29e3aefdc0784dde013e0f2edfe9069
files=(app/content.php app/mcp-chatgpt.php app/mcp-chatgpt-media.php)

sudo -v
pid=$(systemctl show -p MainPID --value "$unit")
python3 - "$pid" "$data" <<'PY'
from pathlib import Path
import sys
pid, data = sys.argv[1:]
if not pid.isdecimal() or int(pid) < 1:
    raise SystemExit("El servicio de laboratorio no está activo.")
if ("UW_DATA=" + data).encode() not in (Path("/proc") / pid / "environ").read_bytes().split(b"\0"):
    raise SystemExit("UW_DATA del proceso no coincide con el laboratorio.")
PY

sudo python3 - "$lab" <<'PY'
from pathlib import Path
import sys
lab = Path(sys.argv[1])
prod = Path("/var/www/universal-web").resolve(strict=True)
for relative, production in (
    ("data/universal.sqlite", "data/universal.sqlite"),
    ("data/config.php", "data/config.php"),
    ("cms/public/media", "public/media"),
):
    local = lab / relative
    source = prod / production
    if local.resolve(strict=True) != local or local.samefile(source):
        raise SystemExit("Ruta compartida o enlazada: " + relative)
    if local.is_dir() and any(path.is_symlink() for path in local.rglob("*")):
        raise SystemExit("Enlace simbólico en multimedia de staging.")
print("staging_paths=OK")
PY

php -r 'exit(function_exists("imagecreatefromstring") && function_exists("imagepng") && function_exists("imagejpeg") ? 0 : 1);'
work=$(mktemp -d "$lab/media-test.XXXXXXXX")
backup=$(mktemp -d "$lab/media-rollback.XXXXXXXX")
trial="$work/cms"
trap 'git -C "$repo" worktree remove "$trial" 2>/dev/null || true; rm -rf -- "$work"' EXIT
git -C "$repo" worktree add --detach "$trial" "$candidate"
mkdir "$work/data"

for file in "${files[@]}"; do php -l "$trial/$file"; done
php "$trial/tests/mcp-chatgpt-readonly.php"
UW_DATA="$work/data" php "$trial/tests/mcp-chatgpt-drafts.php"

for file in app/content.php app/mcp-chatgpt.php; do
  git -C "$repo" show "$candidate^:$file" > "$work/base.php"
  cmp -s "$work/base.php" "$repo/$file" || { echo "Base inesperada: $file"; exit 1; }
  cp -- "$repo/$file" "$backup/${file##*/}"
done
test ! -e "$repo/app/mcp-chatgpt-media.php" && test ! -L "$repo/app/mcp-chatgpt-media.php"
cp -- "$data/config.php" "$backup/config.php"

python3 - "$data/universal.sqlite" "$backup/universal.sqlite" <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
source, dest = map(Path, sys.argv[1:])
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as live:
    with closing(sqlite3.connect(dest)) as copy:
        live.backup(copy)
        if copy.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
            raise SystemExit("La copia SQLite no es autónoma.")
        if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise SystemExit("Falló integrity_check.")
        if copy.execute("PRAGMA foreign_key_check").fetchall():
            raise SystemExit("Falló foreign_key_check.")
print("sqlite_backup=OK")
PY
tar -C "$repo/public" -czf "$backup/media.tar.gz" media
tar -tzf "$backup/media.tar.gz" >/dev/null
(
  cd "$backup"
  sha256sum universal.sqlite media.tar.gz > SHA256SUMS
  sha256sum -c SHA256SUMS
)

php -r '
$cfg = require $argv[1];
$mcp = $cfg["chatgpt_mcp"] ?? [];
if (($mcp["drafts_enabled"] ?? false) !== true
    || ($mcp["host"] ?? null) !== "mcp-staging.carlosbarcelo.es"
    || ($mcp["issuer"] ?? null) !== "https://auth-staging.carlosbarcelo.es/realms/uw-mcp-staging"
    || ($mcp["site_slug"] ?? null) !== "universal-web-mcp-lab") exit(1);
$cfg["chatgpt_mcp"]["draft_media_enabled"] = true;
if (file_put_contents($argv[2], "<?php\nreturn " . var_export($cfg, true) . ";\n") === false) exit(1);
' "$data/config.php" "$work/config.php"
php -l "$work/config.php"

install_atomic() {
  local source=$1 target=$2 mode=$3 temp
  temp=$(mktemp "${target}.XXXXXXXX")
  install -m "$mode" -- "$source" "$temp" && mv -fT -- "$temp" "$target"
}

rollback() {
  install_atomic "$backup/config.php" "$data/config.php" 0600 &&
  install_atomic "$backup/mcp-chatgpt.php" "$repo/app/mcp-chatgpt.php" 0644 &&
  install_atomic "$backup/content.php" "$repo/app/content.php" 0644 &&
  rm -f -- "$repo/app/mcp-chatgpt-media.php" &&
  sudo systemctl restart "$unit"
}

activate() {
  install_atomic "$trial/app/mcp-chatgpt-media.php" "$repo/app/mcp-chatgpt-media.php" 0644 &&
  install_atomic "$trial/app/content.php" "$repo/app/content.php" 0644 &&
  install_atomic "$trial/app/mcp-chatgpt.php" "$repo/app/mcp-chatgpt.php" 0644 &&
  install_atomic "$work/config.php" "$data/config.php" 0600 &&
  sudo systemctl restart "$unit" &&
  curl -fsS --retry 4 --retry-connrefused --max-time 5     -H 'Host: mcp-staging.carlosbarcelo.es'     http://127.0.0.1:8182/.well-known/oauth-protected-resource/mcp/chatgpt |
  python3 -c 'import json, sys; assert set(json.load(sys.stdin)["scopes_supported"]) == {"uw:read", "uw:drafts:write", "uw:drafts:media"}'
}

if ! activate; then
  if rollback; then echo 'Fallo de activación. Fase 2 restaurada.' >&2
  else echo "Fallo de restauración. Copia: $backup" >&2
  fi
  exit 1
fi

printf 'staging_media=OK\nrollback=%s\n' "$backup"
