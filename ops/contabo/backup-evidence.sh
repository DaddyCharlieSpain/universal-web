#!/usr/bin/env bash
set -euo pipefail

# Run locally under an administrator who can read the cron journal.
cron_unit=cron.service
printf 'cron_service=%s\n' "$(systemctl is-active "$cron_unit" 2>/dev/null || true)"
for entry in \
    'universal-web-backup|backup-universal-monitor.sh|0 3' \
    'universal-web-watchdog|check-universal-backup.sh|0 6'; do
    IFS='|' read -r name program schedule <<< "$entry"
    pattern="^[[:space:]]*${schedule/ /[[:space:]]+}[[:space:]]+\\*[[:space:]]+\\*[[:space:]]+\\*[[:space:]]+carlosadmin[[:space:]]+/usr/local/bin/${program/.sh/\\.sh}([[:space:]]|$)"
    result=missing_or_different
    if [[ -r /etc/cron.d/$name ]] && grep -Eq "$pattern" "/etc/cron.d/$name"; then
        result=expected
    fi
    printf '%s_schedule=%s\n' "$name" "$result"
    if ! stamp=$(journalctl -u "$cron_unit" --since '48 hours ago' --no-pager -o short-iso |
        awk -v cmd="/usr/local/bin/$program" 'index($0, "(carlosadmin) CMD (" cmd " ") {stamp=$1} END {print stamp}'); then
        stamp=unavailable
    fi
    printf '%s_last_cron_start=%s\n' "$name" "${stamp:-not_observed}"
done
/usr/bin/php /usr/local/libexec/universal-web/validate-051.php backup-status
