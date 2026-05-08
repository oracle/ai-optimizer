#!/usr/bin/env python3
"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Bootstrap a SigNoz install with the curated dashboards and alert rules
under ``helm/observe/signoz/``. Targets a fresh install or one that has
just been wiped via ``compose down -v``.

Re-running creates duplicates because SigNoz assigns a new id per POST.
The intended workflow is: bootstrap once into a fresh install; further
changes happen in the UI; export back to this directory; bootstrap again
into the next empty install.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOGIN_TIMEOUT_SECONDS = 15
UPLOAD_TIMEOUT_SECONDS = 30
ERROR_BODY_LIMIT = 500

# Targets SigNoz 0.121+.
LOGIN_PATH = "/api/v2/sessions/email_password"
SESSION_CONTEXT_PATH = "/api/v2/sessions/context"
DASHBOARDS_PATH = "/api/v1/dashboards"
RULES_PATH = "/api/v2/rules"


class BootstrapError(Exception):
    """Helpers raise this; main() catches once and turns it into an exit message."""


def _read_json(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None,
               timeout: int = LOGIN_TIMEOUT_SECONDS) -> dict:
    """GET (or POST if ``data`` is set) ``url`` and return the parsed JSON body."""
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            body_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode(errors="replace")[:ERROR_BODY_LIMIT].strip()
        detail = f": {err_body}" if err_body else ""
        raise BootstrapError(f"request to {url} failed: HTTP {exc.code} {exc.reason}{detail}") from exc
    except urllib.error.URLError as exc:
        raise BootstrapError(f"request to {url} failed: cannot reach host: {exc.reason}") from exc

    if not body_bytes:
        raise BootstrapError(f"request to {url} returned an empty body (HTTP {status})")

    try:
        return json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        snippet = body_bytes[:ERROR_BODY_LIMIT].decode(errors="replace").strip()
        raise BootstrapError(
            f"response from {url} was not JSON (HTTP {status}, Content-Type: {content_type or '<unset>'}).\n"
            f"  first {ERROR_BODY_LIMIT} bytes: {snippet!r}\n"
            f"  this usually means --host is reaching the SigNoz frontend HTML page rather than the API.\n"
            f"  verify --host points at the URL you open in the browser, and that this is SigNoz 0.121+."
        ) from exc


def _resolve_org_id(host: str, email: str) -> str:
    """Discover the user's orgId via the session-context endpoint.

    Used when the operator did not pass ``--org-id``. Refuses to guess on
    multi-org accounts: returns one id only when the account belongs to exactly
    one org, otherwise raises with the list so the operator picks explicitly.
    """
    url = (
        host.rstrip("/")
        + SESSION_CONTEXT_PATH
        + "?"
        + urllib.parse.urlencode({"email": email, "ref": host})
    )
    body = _read_json(url)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        keys = sorted(body) if isinstance(body, dict) else type(body).__name__
        raise BootstrapError(f"session-context response missing 'data' object: keys={keys}")
    if not data.get("exists"):
        raise BootstrapError(f"no SigNoz user found for {email}")
    orgs = data.get("orgs") or []
    if not orgs:
        raise BootstrapError(f"no organizations associated with {email}")
    if len(orgs) > 1:
        listing = "\n".join(f"  {o.get('id')}  {o.get('name', '?')}" for o in orgs)
        raise BootstrapError(
            f"{email} belongs to {len(orgs)} organizations; pick one with --org-id "
            f"(or $SIGNOZ_ORG_ID) to avoid posting assets into the wrong org:\n{listing}"
        )
    org_id = orgs[0].get("id")
    if not org_id:
        raise BootstrapError(f"single org in session context has no id: {orgs[0]!r}")
    return org_id


def login(host: str, email: str, password: str, org_id: str | None = None) -> str:
    """Exchange ``email`` + ``password`` for a SigNoz accessToken (0.121+).

    ``org_id`` is required by the login body. If not supplied, the user's org
    is auto-discovered, but only when the account belongs to a single org.
    """
    if org_id is None:
        org_id = _resolve_org_id(host, email)
    payload = json.dumps({"email": email, "password": password, "orgId": org_id}).encode()
    url = host.rstrip("/") + LOGIN_PATH
    body = _read_json(url, data=payload, headers={"Content-Type": "application/json"})

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        keys = sorted(body) if isinstance(body, dict) else type(body).__name__
        raise BootstrapError(f"login response missing 'data' object: keys={keys}")
    token = data.get("accessToken")
    if not token:
        raise BootstrapError(f"login response missing 'accessToken'; keys present: {sorted(data)}")
    return token


def post_file(host: str, token: str, endpoint: str, path: Path) -> tuple[bool, str]:
    """POST a single JSON file to SigNoz; return (success, message)."""
    data = path.read_bytes()
    req = urllib.request.Request(
        host.rstrip("/") + endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT_SECONDS) as resp:  # noqa: S310
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:ERROR_BODY_LIMIT].strip()
        return False, f"HTTP {exc.code}: {body}" if body else f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason)


def load_directory(host: str, token: str, label: str, directory: Path, endpoint: str) -> int:
    """POST every ``*.json`` under ``directory``; return failure count."""
    if not directory.is_dir():
        print(f"  {label} directory not found at {directory}; skipping", file=sys.stderr)
        return 0
    files = sorted(directory.glob("*.json"))
    if not files:
        print(f"  no {label} JSON files in {directory}; skipping")
        return 0

    failures = 0
    for f in files:
        ok, msg = post_file(host, token, endpoint, f)
        marker = "ok" if ok else "FAILED"
        print(f"  {f.name} ... {marker} ({msg})")
        if not ok:
            failures += 1
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap a SigNoz install with the dashboards and alerts under helm/observe/signoz/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  bootstrap-signoz.py --host http://localhost:8080 --email admin@example.com\n"
            "      (prompts for password)\n"
            "  bootstrap-signoz.py --host http://localhost:8080 --token <jwt>\n"
            "      (skip login; useful for CI / SSO)\n"
            "  bootstrap-signoz.py --host http://localhost:8080 --email admin@example.com --alerts-only\n"
            "\n"
            "Each flag falls back to its corresponding environment variable when omitted:\n"
            "  --host    -> SIGNOZ_HOST\n"
            "  --email   -> SIGNOZ_EMAIL\n"
            "  --token   -> SIGNOZ_TOKEN\n"
            "  --org-id  -> SIGNOZ_ORG_ID\n"
            "  password is read from $SIGNOZ_PASSWORD if set, otherwise prompted.\n"
        ),
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SIGNOZ_HOST"),
        help="SigNoz base URL, e.g. http://localhost:8080.",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("SIGNOZ_EMAIL"),
        help="Admin email to log in with. Required unless --token is provided.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SIGNOZ_TOKEN"),
        help="Pre-fetched JWT. Skips the login step.",
    )
    parser.add_argument(
        "--org-id",
        default=os.environ.get("SIGNOZ_ORG_ID"),
        help=(
            "SigNoz organization UUID for multi-org accounts. Optional for single-org "
            "installs (auto-discovered). Required when the email belongs to multiple orgs."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dashboards-only", action="store_true", help="Only load dashboards/*.json")
    mode.add_argument("--alerts-only", action="store_true", help="Only load alerts/*.json")
    mode.add_argument(
        "--print-token",
        action="store_true",
        help="Log in, print the JWT, and exit. Useful for ad-hoc curl debugging.",
    )
    return parser.parse_args(argv)


def resolve_password(email: str) -> str:
    """Read password from $SIGNOZ_PASSWORD or prompt interactively.

    Password input is supported via the interactive prompt or
    ``SIGNOZ_PASSWORD``; the script intentionally does not provide a
    ``--password`` flag.
    """
    pw = os.environ.get("SIGNOZ_PASSWORD")
    if pw:
        return pw
    try:
        return getpass.getpass(f"SigNoz password for {email}: ")
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        sys.exit(130)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.host:
        sys.exit("--host (or $SIGNOZ_HOST) is required")

    try:
        if args.token:
            token = args.token
        else:
            if not args.email:
                sys.exit("--email (or $SIGNOZ_EMAIL) required when --token is not provided")
            password = resolve_password(args.email)
            if not password:
                sys.exit("password is required")
            print(f"Authenticating to {args.host} as {args.email}...", file=sys.stderr)
            token = login(args.host, args.email, password, org_id=args.org_id)
    except BootstrapError as exc:
        sys.exit(str(exc))

    if args.print_token:
        # stdout-only so $(...) capture works; auth status went to stderr above.
        print(token)
        return 0

    repo_root = Path(__file__).resolve().parents[2]
    assets_root = repo_root / "helm" / "observe" / "signoz"
    print(f"Bootstrapping SigNoz at {args.host}")

    failures = 0
    if not args.alerts_only:
        print("\nDashboards:")
        failures += load_directory(args.host, token, "dashboard", assets_root / "dashboards", DASHBOARDS_PATH)
    if not args.dashboards_only:
        print("\nAlerts:")
        failures += load_directory(args.host, token, "alert", assets_root / "alerts", RULES_PATH)

    print()
    if failures > 0:
        print(f"Bootstrap completed with {failures} failure(s).", file=sys.stderr)
        return 1

    print(f"Bootstrap complete. Verify in the UI: {args.host}")
    print("Reminder: alerts have no notification channel attached — set one per alert in the UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
