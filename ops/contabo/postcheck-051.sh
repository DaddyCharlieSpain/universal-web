#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 3 || ! $1 =~ ^[a-zA-Z0-9.-]+$ || $2 != /* || $3 != /* ||
      $2 == //* || $3 == //* ]]; then
    echo "Usage: $0 CMS_HOST KNOWN_PUBLISHED_PATH KNOWN_MEDIA_OR_THEME_PATH" >&2
    exit 64
fi

host=$1
shift
for path in / /admin "$1" "$2"; do
    code=$(curl --silent --show-error --max-time 15 --noproxy '*' \
        --resolve "$host:443:127.0.0.1" --output /dev/null --write-out '%{http_code}' \
        "https://$host$path")
    case "$path:$code" in
        /admin:200|/admin:302|/admin:303|*:200) ;;
        *) printf 'http_check=FAIL status=%s\n' "$code" >&2; exit 1 ;;
    esac
done
echo 'http_check=OK'
