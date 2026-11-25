# Cloudflare Pages publisher (Linux/systemd)

Draft integration for Universal Web 0.5.1. One site per publisher instance. Requires Bash, PHP CLI, Python 3, GNU coreutils, util-linux, tar and Wrangler at /usr/bin/wrangler. CMS code must be trusted and protected from web-user modification. Configure static/download publication, matching public URL, and disable native auto_publish. The timer consumes site_publish.dirty; verify that your CMS marks content dirty on publication.

## Installation

Review and test in an isolated environment before enabling. Do not install over an existing working publisher without a backup. Stop the timer and wait for any running service before replacing files.

```sh
sudo install -d -m 700 /etc/uw-pages-publish /var/lib/uw-pages-publish
sudo install -m 600 publisher.env.example /etc/uw-pages-publish/publisher.env
sudo install -m 600 cloudflare.env.example /etc/uw-pages-publish/cloudflare.env
sudoedit /etc/uw-pages-publish/publisher.env
sudoedit /etc/uw-pages-publish/cloudflare.env
sudo install -m 750 uw-pages-publish.sh /usr/local/sbin/uw-pages-publish.sh
sudo install -m 644 uw-pages-publish.service uw-pages-publish.timer /etc/systemd/system/
sudo bash -n /usr/local/sbin/uw-pages-publish.sh
sudo systemctl daemon-reload
sudo systemctl enable --now uw-pages-publish.timer
```

Run installation from this directory as an administrator on a fresh installation only. Set the actual project, slug, public URL, branch and CMS version. The credential file is root-only; use an account-scoped Pages Edit token with the narrowest supported permissions. Never commit actual configuration or credentials. Wrangler runs as root; the renderer runs as www-data without token access. Disable competing deployments to the same production branch.

## Operation

```sh
sudo systemctl list-timers uw-pages-publish.timer
sudo journalctl -u uw-pages-publish.service --no-pager -n 50
```

A successful deployment logs pages_publish=OK and its URL. Idle runs do not deploy. Failures retain an in-progress marker for retry. The static snapshot rejects links, special files, hidden entries and unsupported extensions. No server-side application or database is intentionally published.

## Recovery

Stop the timer, wait for the service to finish, restore backed-up scripts and unit files, reload systemd and restart the timer. Preserve pending markers and CMS data. For a public-site rollback, pause publishing first and select a previous production deployment in Cloudflare Pages; reconcile CMS content before resuming to avoid overwriting the rollback.

## Validation status and limitations

The site-specific predecessor was exercised in production and its controlled extractor passed ten isolated positive/negative tests. This generic adaptation has not been deployed or independently tested. Verify syntax, archive handling, dirty-flag concurrency, retry behavior, deployment URL parsing, resource limits and CMS compatibility before use. The current design is not a full security audit; root execution and account-level token scope warrant review. No automatic upgrade across CMS versions is implied.
