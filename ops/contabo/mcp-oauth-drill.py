#!/usr/bin/env python3
"""Run against the synthetic Contabo lab. Credentials stay in local memory."""
from contextlib import closing
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import quote_plus, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

REALM = "uw-mcp-staging"
ISSUER = f"https://auth-staging.carlosbarcelo.es/realms/{REALM}"
MCP_HOST = "mcp-staging.carlosbarcelo.es"
RESOURCE = f"https://{MCP_HOST}/mcp/chatgpt"
LAB = Path.home() / "uw-mcp-staging/universal-web-lab.vn9bJ6yw"
ROOT = Path(__file__).resolve().parents[2]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


http = build_opener(ProxyHandler({}), NoRedirect())
# Match the CMS cURL request, which does not set a User-Agent.
http.addheaders = []


def request(url, data=None, headers=None):
    try:
        result = http.open(Request(url, data=data, headers=headers or {}), timeout=8)
    except HTTPError as error:
        result = error
    with closing(result):
        raw = result.read(65537)
        return result.status, json.loads(raw) if raw and raw.lstrip().startswith(b"{") else {}


def log(event, **fields):
    print(datetime.now(timezone.utc).isoformat(timespec="seconds"), event,
          *(f"{key}={value}" for key, value in fields.items()), flush=True)


def require(condition, label):
    if not condition:
        raise RuntimeError(label)


def main():
    os.umask(0o077)
    require(ROOT.is_relative_to(LAB.parent.resolve()), "checkout_not_under_staging")
    base = LAB / "data"
    for name in ("universal.sqlite", "config.php"):
        path = base / name
        require(path.resolve(strict=True) == path, "unsafe_lab_path")
    binaries = list(LAB.parent.glob("**/keycloak-26.8.2/bin/kcadm.sh"))
    require(len(binaries) == 1, "unique_kcadm_required")
    php = shutil.which("php")
    require(bool(php), "php_required")

    with tempfile.TemporaryDirectory(prefix="oauth-drill-", dir=LAB) as directory:
        work = Path(directory)
        data = work / "data"
        data.mkdir()
        credentials = work / "kcadm.config"
        client = "uw-mcp-drill-" + secrets.token_hex(8)
        client_id = None
        server = None

        def admin(*args, payload=None, interactive=False):
            command = [str(binaries[0]), *args, "--config", str(credentials)]
            if interactive:
                with open("/dev/tty") as tty:
                    subprocess.run(command, stdin=tty, check=True)
                return ""
            result = subprocess.run(command, input=json.dumps(payload) if payload is not None else "",
                                    text=True, capture_output=True)
            require(result.returncode == 0, f"kcadm_{args[0]}_failed")
            return result.stdout.strip()

        def db_state():
            with closing(sqlite3.connect((data / "universal.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
                require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "sqlite_integrity")
                require(not db.execute("PRAGMA foreign_key_check").fetchall(), "sqlite_foreign_keys")
                return hashlib.sha256("\n".join(db.iterdump()).encode()).digest()

        try:
            with closing(sqlite3.connect((base / "universal.sqlite").as_uri() + "?mode=ro", uri=True)) as source:
                require(source.execute("SELECT COUNT(*) FROM sites WHERE slug = 'universal-web-mcp-lab'").fetchone() == (1,),
                        "synthetic_site_not_found")
                with closing(sqlite3.connect(data / "universal.sqlite")) as dest:
                    source.backup(dest)
            before = db_state()
            admin("config", "credentials", "--server", "http://127.0.0.1:8180",
                  "--realm", "master", "--user", "staging-admin", interactive=True)
            scope_list = json.loads(admin("get", "client-scopes", "-r", REALM, "--fields", "id,name"))
            scopes = {entry["name"]: entry["id"] for entry in scope_list}
            require({"basic", "uw:read"} <= scopes.keys(), "required_scopes_missing")
            client_id = admin("create", "clients", "-r", REALM, "-i", "-f", "-", payload={
                "clientId": client, "protocol": "openid-connect", "enabled": True,
                "clientAuthenticatorType": "client-secret", "publicClient": False,
                "standardFlowEnabled": False, "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False, "serviceAccountsEnabled": True,
                "fullScopeAllowed": False, "defaultClientScopes": ["basic"], "optionalClientScopes": [],
                "attributes": {"access.token.lifespan": "30", "resource_url": RESOURCE},
            })
            require(bool(client_id), "disposable_client_not_created")
            log("disposable_client", created=client)
            admin("update", f"clients/{client_id}/optional-client-scopes/{scopes['uw:read']}", "-r", REALM, "-n")
            admin("create", f"clients/{client_id}/protocol-mappers/models", "-r", REALM, "-f", "-", payload={
                "name": "staging MCP audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                "config": {"included.custom.audience": RESOURCE, "access.token.claim": "true",
                           "introspection.token.claim": "true"},
            })
            secret = json.loads(admin("get", f"clients/{client_id}/client-secret", "-r", REALM))["value"]
            subject = json.loads(admin("get", f"clients/{client_id}/service-account-user", "-r", REALM, "--fields", "id"))["id"]

            php_config = r"""
$cfg = require $argv[1];
$m = $cfg['chatgpt_mcp'] ?? [];
if (($m['host'] ?? null) !== 'mcp-staging.carlosbarcelo.es'
    || ($m['site_slug'] ?? null) !== 'universal-web-mcp-lab'
    || ($m['issuer'] ?? null) !== $argv[5]
    || ($m['introspection_url'] ?? null) !== $argv[5] . '/protocol/openid-connect/token/introspect') exit(1);
$m['client_id'] = $argv[3];
$m['subject'] = $argv[4];
$m['drafts_enabled'] = false;
$m['draft_media_enabled'] = false;
$output = "<?php\nreturn " . var_export(['chatgpt_mcp' => $m], true) . ";\n";
if (file_put_contents($argv[2], $output, LOCK_EX) === false) exit(1);
echo json_encode([$m['introspection_id'], $m['introspection_secret']]);
"""
            config = subprocess.run([php, "-r", php_config, str(base / "config.php"), str(data / "config.php"),
                                     client, subject, ISSUER], capture_output=True, check=True)
            inspection_id, inspection_secret = json.loads(config.stdout)
            authorization = base64.b64encode(
                (quote_plus(inspection_id) + ":" + quote_plus(inspection_secret)).encode()
            ).decode()

            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = subprocess.Popen([php, "-S", f"127.0.0.1:{port}", "-t", str(ROOT / "public"),
                                       str(ROOT / "public/index.php")], env={**os.environ, "UW_DATA": str(data)},
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(30):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("loopback_mcp_not_ready")

            protocol = f"http://127.0.0.1:8180/realms/{REALM}/protocol/openid-connect"

            def keycloak(endpoint, fields):
                return request(f"{protocol}/{endpoint}", urlencode({
                    "client_id": client, "client_secret": secret, **fields,
                }).encode(), {"Content-Type": "application/x-www-form-urlencoded",
                              "Host": "auth-staging.carlosbarcelo.es", "X-Forwarded-Proto": "https",
                              "X-Forwarded-Host": "auth-staging.carlosbarcelo.es", "X-Forwarded-Port": "443"})

            def inspect(token, public=True):
                endpoint = f"{ISSUER}/protocol/openid-connect" if public else protocol
                headers = {"Content-Type": "application/x-www-form-urlencoded",
                           "Authorization": "Basic " + authorization}
                if not public:
                    headers.update({"Host": "auth-staging.carlosbarcelo.es",
                                    "X-Forwarded-Proto": "https",
                                    "X-Forwarded-Host": "auth-staging.carlosbarcelo.es",
                                    "X-Forwarded-Port": "443"})
                return request(f"{endpoint}/token/introspect",
                               urlencode({"token": token, "token_type_hint": "access_token"}).encode(), headers)

            def read(token):
                return request(f"http://127.0.0.1:{port}/mcp/chatgpt", json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "post_list", "arguments": {"limit": 1}},
                }).encode(), {"Host": MCP_HOST, "Content-Type": "application/json", "Authorization": "Bearer " + token})

            def issue(label):
                status, payload = keycloak("token", {"grant_type": "client_credentials", "scope": "uw:read", "resource": RESOURCE})
                log(label + "_issue", http=status)
                token = payload.get("access_token")
                require(status == 200 and isinstance(token, str), "token_issue_failed")
                parts = token.split(".")
                require(len(parts) == 3, "expected_jwt_access_token")
                encoded = parts[1]
                unverified = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
                audience = unverified.get("aud", [])
                audience = [audience] if isinstance(audience, str) else audience
                audience_ok = isinstance(audience, list) and inspection_id in audience and RESOURCE in audience
                log(label + "_audience", matches=audience_ok)
                require(audience_ok, "issued_token_missing_resource_audience")
                status, claims = inspect(token)
                known_errors = {"invalid_request", "invalid_client", "invalid_token", "access_denied", "insufficient_scope"}
                error = claims.get("error")
                log(label + "_introspection", http=status, active=claims.get("active"),
                    oauth_error=error if isinstance(error, str) and error in known_errors else "-")
                if status != 200:
                    local_status, local_claims = inspect(token, public=False)
                    log(label + "_keycloak_loopback", http=local_status, active=local_claims.get("active"))
                    mcp_status, _ = read(token)
                    log(label + "_mcp_curl", http=mcp_status)
                require(status == 200 and claims.get("active") is True, "valid_token_inactive")
                require(0 < claims["exp"] - time.time() <= 60, "unexpected_token_lifetime")
                status, response = read(token)
                result = response.get("result", {})
                ok = result.get("isError") is False and "posts" in result.get("structuredContent", {})
                log(label + "_read", http=status, authorized=ok)
                require(status == 200 and ok, "valid_read_failed")
                return token, claims["exp"]

            expiring, deadline = issue("expiry")
            time.sleep(max(0, deadline - time.time() + 2))
            status, claims = inspect(expiring)
            log("expired_introspection", http=status, active=claims.get("active"))
            require(status == 200 and claims.get("active") is False, "expired_introspection_failed")
            status, _ = read(expiring)
            log("expired_read", http=status)
            require(status == 401, "expired_mcp_not_rejected")

            revokable, deadline = issue("revocation")
            status, _ = keycloak("revoke", {"token": revokable, "token_type_hint": "access_token"})
            log("token_revocation", http=status)
            require(status == 200, "revocation_request_failed")
            status, claims = inspect(revokable)
            log("revoked_introspection", http=status, active=claims.get("active"))
            require(status == 200 and claims.get("active") is False, "revoked_introspection_failed")
            status, _ = read(revokable)
            log("revoked_read", http=status)
            require(status == 401 and time.time() < deadline, "revocation_not_distinguished_from_expiry")
            require(db_state() == before, "sqlite_rows_changed")
            log("sqlite", integrity="OK", foreign_keys="OK", rows="UNCHANGED")
        finally:
            if server:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
            if client_id:
                admin("delete", f"clients/{client_id}", "-r", REALM)
                clients = json.loads(admin("get", "clients", "-r", REALM, "-q", f"clientId={client}", "--fields", "clientId"))
                require(all(item["clientId"] != client for item in clients), "disposable_client_still_exists")
                log("disposable_client", removed="OK")

    log("oauth_drill", result="OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Exception arguments from HTTP, subprocess, and JSON may contain private input.
        log("oauth_drill", result="FAIL", kind=type(error).__name__,
            check=str(error) if type(error) is RuntimeError else "see_previous_stage")
        raise SystemExit(1) from None
