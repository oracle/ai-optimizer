"""Administrative CLI for local AI Optimizer accounts."""

from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from server.app.auth.service import GatewayConfig, GatewayService
from server.app.auth.store import OracleAuthStore
from server.app.core.secrets import reveal
from server.app.core.settings import settings
from server.app.database.config import get_database_settings
from server.app.database.registry import init_core_database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local AI Optimizer accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    add_user = commands.add_parser("add-user", help="Create a local user")
    add_user.add_argument("--username", required=True)
    add_user.add_argument("--display-name", required=True)
    add_user.add_argument("--email")
    add_user.add_argument("--administrator", action="store_true")
    set_password = commands.add_parser("set-password", help="Set a local user password")
    set_password.add_argument("username")
    set_active = commands.add_parser("set-active", help="Enable or disable a local user")
    set_active.add_argument("username")
    set_active.add_argument("active", choices=("true", "false"))
    role = commands.add_parser("set-administrator", help="Grant or revoke aio.admin")
    role.add_argument("username")
    role.add_argument("enabled", choices=("true", "false"))
    commands.add_parser("list-users", help="List local users")
    return parser


async def _service() -> GatewayService:
    if settings.auth_mode != "local":
        raise RuntimeError("Set AIO_AUTH_MODE=local before managing local accounts")
    core_database = get_database_settings(settings.database_configs, "CORE")
    if core_database is None:
        raise RuntimeError("A CORE database configuration is required")
    await init_core_database(core_database)
    service = GatewayService(
        GatewayConfig(
            issuer=settings.auth_issuer,
            mode="local",
            web_client_secret=reveal(settings.auth_web_client_secret) or "",
            web_redirect_uri=settings.auth_web_redirect_uri,
            local_admin_username=settings.auth_local_admin_username,
            local_admin_password=reveal(settings.auth_local_admin_password) or "",
            access_token_minutes=settings.auth_access_token_minutes,
            login_session_hours=settings.auth_login_session_hours,
        ),
        OracleAuthStore(),
    )
    await service.initialize()
    return service


async def _run(args: argparse.Namespace) -> None:
    service = await _service()
    if args.command == "add-user":
        password = getpass("Password: ")
        if password != getpass("Confirm password: "):
            raise ValueError("Passwords do not match")
        await service.create_local_account(
            username=args.username,
            password=password,
            display_name=args.display_name,
            email=args.email,
            administrator=args.administrator,
        )
        return
    if args.command == "set-password":
        password = getpass("Password: ")
        if password != getpass("Confirm password: "):
            raise ValueError("Passwords do not match")
        await service.set_local_password(args.username, password)
        return
    if args.command in {"set-active", "set-administrator"}:
        principal = await service.local_principal(args.username)
        if principal is None:
            raise ValueError("Unknown local user")
        if args.command == "set-active":
            await service.store.set_principal_active(principal.principal_id, args.active == "true")
        else:
            await service.store.set_role(principal.principal_id, "aio.admin", "local-admin", args.enabled == "true")
        return
    for principal in await service.store.list_principals():
        print(f"{principal.principal_id}\t{principal.display_name}\t{principal.email or ''}\t{principal.active}")


def main() -> None:
    """Run local account administration."""
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
