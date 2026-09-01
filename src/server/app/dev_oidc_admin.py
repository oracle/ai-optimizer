"""Small command-line provisioner for built-in development OIDC users."""

from __future__ import annotations

import argparse
import asyncio
from getpass import getpass
from pathlib import Path

from dev_auth_credentials import read_bootstrap_credential
from server.app.core.dev_oidc import DevelopmentOidcService, OracleDevelopmentOidcStore
from server.app.core.secrets import reveal
from server.app.core.settings import settings
from server.app.database.config import get_database_settings
from server.app.database.registry import init_core_database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision a built-in development OIDC user")
    subcommands = parser.add_subparsers(dest="command", required=True)
    add_user = subcommands.add_parser("add-user", help="Create a development user")
    add_user.add_argument("--username", required=True)
    add_user.add_argument("--email", required=True)
    add_user.add_argument("--display-name", required=True)
    add_user.add_argument("--administrator", action="store_true")
    subcommands.add_parser(
        "show-bootstrap-password", help="Show the locally generated bootstrap administrator credential"
    )
    return parser


def _show_bootstrap_password() -> None:
    """Print the launcher-generated development administrator credential."""
    script_dir = Path(__file__).resolve().parents[2]
    credential = read_bootstrap_credential(script_dir)
    if credential is None:
        raise RuntimeError(
            "No locally generated development bootstrap credential exists. "
            "Set AIO_AUTH_DEV_ADMIN_PASSWORD or start All-In-One with a CORE database first."
        )
    print(f"Username: {credential.username}")
    print(f"Password: {credential.password}")


async def _add_user(args: argparse.Namespace) -> None:
    core_database = get_database_settings(settings.database_configs, "CORE")
    if core_database is None:
        raise RuntimeError("A CORE database configuration is required")
    await init_core_database(core_database)
    service = DevelopmentOidcService(
        issuer=settings.auth_dev_issuer,
        store=OracleDevelopmentOidcStore(),
        seed_passwords={
            "admin@example.test": reveal(settings.auth_dev_admin_password) or "",
        },
        web_client_secret=reveal(settings.auth_dev_web_client_secret) or "",
        web_client_redirect_uri=settings.auth_dev_web_redirect_uri,
    )
    await service.initialize()
    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match")
    await service.provision_user(
        username=args.username,
        email=args.email,
        display_name=args.display_name,
        password=password,
        administrator=args.administrator,
    )


def main() -> None:
    """Run the development-user provisioning command."""
    args = _parser().parse_args()
    if args.command == "add-user":
        asyncio.run(_add_user(args))
    elif args.command == "show-bootstrap-password":
        _show_bootstrap_password()


if __name__ == "__main__":
    main()
