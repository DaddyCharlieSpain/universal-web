#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
export PATH=/usr/bin:/bin
unset CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID
state=/var/lib/uw-pages-publish
config=/etc/uw-pages-publish/publisher.env
credentials=/etc/uw-pages-publish/cloudflare.env
[[ $EUID == 0 && $# == 0 ]]
[[ ! -L $state && $(stat -c '%u:%a' "$state") == 0:700 ]]
[[ $(stat -c '%u:%a' /etc/uw-pages-publish) == 0:700 ]]
for f in "$config" "$credentials"; do
  [[ -f $f && ! -L $f && $(stat -c '%u:%a' "$f") == 0:600 ]]
done
source "$config"
project=${UW_PAGES_PROJECT:?}
slug=${UW_SITE_SLUG:?}
public_url=${UW_PUBLIC_URL:?}
branch=${UW_PAGES_BRANCH:?}
version=${UW_EXPECTED_VERSION:?}
live=${UW_ROOT:?}
[[ $project =~ ^[a-z0-9][a-z0-9-]*$ && $live == /* ]]
exec 9>"$state/lock"
flock -n 9 || exit 0
work=$(mktemp -d /var/tmp/uw-pages.XXXXXXXX)
chown www-data:www-data "$work"
pending=0
stage=export
cms_php() {
  /usr/sbin/runuser -u www-data -- env -i PATH=/usr/bin:/bin UW_DATA="$live/data" \
    /usr/bin/php -d display_errors=0 -d log_errors=0 -- "$live" "$slug" "$work" "$public_url" "$version"
}
requeue() {
  cms_php <<'PHP'
<?php
require $argv[1] . '/app/bootstrap.php';
q('UPDATE site_publish SET dirty=1 WHERE site_id=(SELECT id FROM sites WHERE slug=?)', [$argv[2]]);
PHP
}
cleanup() {
  local code=$?
  trap - EXIT
  if (( pending )); then requeue >/dev/null 2>&1 || echo 'pages_publish=FAIL stage=requeue' >&2; fi
  rm -rf -- "$work"
  if [[ -n ${snapshot:-} ]]; then rm -rf -- "$snapshot"; fi
  if (( code )); then printf 'pages_publish=FAIL stage=%s\n' "$stage" >&2; fi
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ -f "$state/in-progress" ]]; then requeue; fi
touch "$state/in-progress"
export_result=$(cms_php <<'PHP'
<?php
require $argv[1] . '/app/bootstrap.php';
$site = site_by_slug($argv[2]);
if (!$site || UW_VERSION !== $argv[5]) exit(1);
$config = publish_config_raw((int) $site['id']);
if ($config['mode'] !== 'static' || $config['target'] !== 'download'
    || $config['public_url'] !== $argv[4] || $config['auto_publish']) exit(1);
$id = (int) $site['id'];
if (q('UPDATE site_publish SET dirty=0 WHERE dirty=1 AND site_id=?', [$id])->rowCount() !== 1) {
    echo 'idle';
    exit;
}
$build = null;
try {
    [$build] = publish_build(new SiteService($site));
    $command = '/usr/bin/mv -T -- ' . escapeshellarg($build)
        . ' ' . escapeshellarg($argv[3] . '/static');
    exec($command, $moveOutput, $moveStatus);
    if ($moveStatus !== 0) throw new RuntimeException('Error moving static export');
    $build = null;
    echo 'ready';
} catch (Throwable $e) {
    fwrite(STDERR, "EXPORT ERROR: static build failed" . PHP_EOL);
    q('UPDATE site_publish SET dirty=1 WHERE site_id=?', [$id]);
    exit(1);
} finally {
    if ($build !== null) publish_rmtree($build);
}
PHP
)
[[ $export_result != idle ]] || { rm -f "$state/in-progress"; exit 0; }
pending=1
[[ $export_result == ready ]]
stage=snapshot
snapshot=$(mktemp -d "$state/snapshot.XXXXXXXX")
/usr/sbin/runuser -u www-data -- tar -C "$work/static" -cf - . |
    python3 -c '
import sys, tarfile, pathlib, shutil
root = pathlib.Path(sys.argv[1])
allowed = set(".html .css .js .json .xml .txt .md .webp .png .jpg .jpeg .svg .gif .ico .woff .woff2 .avif".split())
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
    for member in archive:
        rel = pathlib.PurePosixPath(member.name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Unsafe archive path")
        if not rel.parts:
            if not member.isdir():
                raise ValueError("Invalid root entry")
            continue
        if rel.parts == (".uw-published",) and member.isfile():
            continue
        if any(part.startswith(".") for part in rel.parts):
            raise ValueError("Hidden archive entry")
        target = root.joinpath(*rel.parts)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        elif member.isfile() and not member.issparse():
            if target.suffix.lower() not in allowed:
                raise ValueError("Unsupported file extension")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source:
                with target.open("xb") as output:
                    shutil.copyfileobj(source, output)
        else:
            raise ValueError("Forbidden archive entry type")
print("SNAPSHOT: OK")
' "$snapshot"
stage=validate
python3 - "$snapshot" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
allowed = set(".html .css .js .json .xml .txt .md .webp .png .jpg .jpeg .svg .gif .ico .woff .woff2 .avif".split())
if not (root / "index.html").is_file():
    sys.exit("VALIDATION ERROR: index.html missing")
for p in root.rglob("*"):
    rel = p.relative_to(root)
    if p.is_symlink() or any(part.startswith(".") for part in rel.parts):
        sys.exit("VALIDATION ERROR: forbidden path")
    if p.is_file() and p.suffix.lower() not in allowed:
        sys.exit("VALIDATION ERROR: unsupported file")
    if not (p.is_file() or p.is_dir()):
        sys.exit("VALIDATION ERROR: invalid file type")
print("VALIDATION: OK")
PY
stage=deploy
set -a
source "$credentials"
set +a
: "${CLOUDFLARE_API_TOKEN:?}" "${CLOUDFLARE_ACCOUNT_ID:?}"
cd "$state"
output=$(/usr/bin/wrangler pages deploy "$snapshot" --project-name "$project" --branch "$branch" 2>&1) || exit 1
url=$(printf '%s\n' "$output" | grep -Eo 'https://[a-z0-9]+\.[a-z0-9-]+\.pages\.dev' | tail -1)
[[ $url == https://*."$project".pages.dev ]]
rm -f "$state/in-progress"
pending=0
printf 'pages_publish=OK url=%s\n' "$url"
