"""Offline recovery for the reserved Admin credential mapping."""

import asyncio
import getpass
import logging
import os
import sys

from server.app.auth.local import database_account_status, normalize_database_username, verify_database_credentials
from server.app.auth.repository import recover_admin_identity
from server.app.core.settings import require_core_database_config, settings, validate_auth_configuration
from server.app.database.config import close_pool
from server.app.database.registry import init_core_database

LOGGER = logging.getLogger(__name__)


async def recover_admin() -> None:
    validate_auth_configuration(settings)
    core = require_core_database_config()
    await init_core_database(core)
    try:
        if settings.auth_mode == "oidc":
            subject = os.getenv("AIO_RECOVERY_OIDC_ADMIN_SUBJECT")
            if not subject:
                raise ValueError("AIO_RECOVERY_OIDC_ADMIN_SUBJECT is required")
            await recover_admin_identity(settings.installation_id or "", oidc_subject=subject)
            return

        username = normalize_database_username(os.getenv("AIO_RECOVERY_ADMIN_DATABASE_USERNAME", ""))
        password = os.environ.pop("AIO_RECOVERY_ADMIN_PASSWORD", None)
        if not password:
            password = getpass.getpass(f"Password for replacement Admin end user {username}: ")
        await verify_database_credentials(username, password)
        if await database_account_status(username) != "OPEN":
            raise ValueError("Replacement Admin is not an open application-managed end user")
        await recover_admin_identity(settings.installation_id or "", database_username=username)
    finally:
        await close_pool(core.pool)
        core.pool = None
        core.usable = False


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(recover_admin())
    except Exception as exc:
        LOGGER.error("Admin recovery failed: %s", exc)
        return 1
    LOGGER.info("Reserved Admin mapping recovered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
