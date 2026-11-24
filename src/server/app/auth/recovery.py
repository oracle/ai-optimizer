"""Offline recovery for the reserved Admin credential mapping."""

import asyncio
import logging
import os
import sys

from server.app.auth.repository import recover_oidc_admin_subject
from server.app.core.settings import require_core_database_config, settings, validate_auth_authority_configuration
from server.app.database.config import close_pool
from server.app.database.registry import init_core_database

LOGGER = logging.getLogger(__name__)


async def recover_admin() -> None:
    validate_auth_authority_configuration(settings)
    core = require_core_database_config()
    await init_core_database(core)
    try:
        if settings.auth_mode != "oidc":
            raise ValueError("Offline Admin recovery is available only for OIDC")
        subject = os.getenv("AIO_RECOVERY_OIDC_ADMIN_SUBJECT")
        if not subject:
            raise ValueError("AIO_RECOVERY_OIDC_ADMIN_SUBJECT is required")
        await recover_oidc_admin_subject(subject)
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
    LOGGER.info("OIDC Admin subject recovered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
