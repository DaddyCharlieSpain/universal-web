#!/usr/bin/env bash
set -euo pipefail

result=/var/lib/universal-web-drill/functional-051.status
expected='functional_051=OK isolation=OK http=OK auth=OK admin=OK content=OK media=OK theme=OK'
if [[ ! -f $result || -L $result || $(stat -c '%u:%a' "$result") != 0:644 ]]; then
    echo 'functional_051=UNAVAILABLE'
    exit 1
fi
now=$(date +%s)
stamp=$(stat -c '%Y' "$result")
if (( stamp > now || now - stamp > 86400 )); then
    echo 'functional_051=STALE'
    exit 1
fi
if [[ $(stat -c '%s' "$result") == $(("${#expected}" + 1)) ]] &&
    cmp -s "$result" <(printf '%s\n' "$expected"); then
    printf '%s\n' "$expected"
    printf 'result_recorded_at=%s\n' "$(date -u -d "@$stamp" +%FT%TZ)"
else
    echo 'functional_051=UNVERIFIED'
    exit 1
fi
