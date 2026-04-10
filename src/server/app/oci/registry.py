"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI profile registry and startup lifecycle.
"""
# spell-checker: ignore genai

import logging
import os
from typing import cast, get_args

from server.app.core.settings import settings

from .config import _check_usable, parse_oci_config_file
from .schemas import OciAuthType, OciProfileConfig
from .service import create_genai_models

LOGGER = logging.getLogger(__name__)

# Mapping of OCI CLI env vars to (settings_attr, profile_field, is_sensitive).
# Precedence: OCI_CLI_* env var > AIO_OCI_CLI_* setting > config file value.
_OCI_CLI_FIELD_MAP: list[tuple[str, str, str, bool]] = [
    # (env_var, settings_attr, profile_field, is_sensitive)
    ("OCI_CLI_TENANCY", "oci_cli_tenancy", "tenancy", False),
    ("OCI_CLI_REGION", "oci_cli_region", "region", False),
    ("OCI_CLI_USER", "oci_cli_user", "user", False),
    ("OCI_CLI_FINGERPRINT", "oci_cli_fingerprint", "fingerprint", True),
    ("OCI_CLI_KEY_FILE", "oci_cli_key_file", "key_file", False),
    ("OCI_CLI_KEY_CONTENT", "oci_cli_key_content", "key_content", True),
    ("OCI_CLI_PASSPHRASE", "oci_cli_passphrase", "pass_phrase", True),
    ("OCI_CLI_SECURITY_TOKEN_FILE", "oci_cli_security_token_file", "security_token_file", True),
]


def register_oci_profile(profile: OciProfileConfig) -> None:
    """Append *profile* to settings.oci_configs (deduplicate by auth_profile, last-write wins)."""
    key = profile.auth_profile.casefold()
    settings.oci_configs = [p for p in settings.oci_configs if p.auth_profile.casefold() != key] + [profile]


def _resolve_oci_cli_auth() -> OciAuthType | None:
    """Resolve OCI_CLI_AUTH from environment, preferring the raw env var over AIO_ prefix.

    Precedence: OCI_CLI_AUTH (export) > AIO_OCI_CLI_AUTH (.env / export) > None
    """
    valid = get_args(OciAuthType)
    raw = os.environ.get("OCI_CLI_AUTH") or settings.oci_cli_auth
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized not in valid:
        LOGGER.warning("Ignoring invalid OCI_CLI_AUTH value '%s' (valid: %s)", raw, ", ".join(valid))
        return None
    return cast(OciAuthType, normalized)


def _apply_oci_cli_overrides(profile: OciProfileConfig) -> bool:
    """Apply OCI_CLI_* / AIO_OCI_CLI_* env var overrides to a profile.

    Returns True if any field was changed.
    """
    changed = False
    overrides_log: list[str] = []

    for env_var, settings_attr, field, sensitive in _OCI_CLI_FIELD_MAP:
        val = os.environ.get(env_var) or getattr(settings, settings_attr, None)
        if val is None:
            continue
        if field in ("key_file", "security_token_file"):
            val = os.path.expanduser(val)
        current = getattr(profile, field)
        if val != current:
            setattr(profile, field, val)
            # key_file and key_content are mutually exclusive in init_client
            if field == "key_file":
                profile.key_content = None
            elif field == "key_content":
                profile.key_file = None
            changed = True
            if sensitive:
                overrides_log.append(f"  {field}: <redacted>")
            else:
                overrides_log.append(f"  {field}: '{current}' -> '{val}'")

    if overrides_log:
        LOGGER.info(
            "OCI DEFAULT profile field overrides from environment:\n%s",
            "\n".join(overrides_log),
        )

    return changed


def apply_env_overrides() -> None:
    """Apply environment overrides to OCI profiles.

    OCI_CLI_* / AIO_OCI_CLI_* override fields on the DEFAULT profile.
    AIO_GENAI_* values override GenAI settings on all profiles.
    """
    auth_override = _resolve_oci_cli_auth()
    has_field_overrides = any(
        os.environ.get(env_var) or getattr(settings, settings_attr, None)
        for env_var, settings_attr, _, _ in _OCI_CLI_FIELD_MAP
    )

    default = next((p for p in settings.oci_configs if p.auth_profile.casefold() == "default"), None)

    if default is None and (auth_override or has_field_overrides):
        LOGGER.info("Creating OCI DEFAULT profile from environment variables")
        default = OciProfileConfig(auth_profile="DEFAULT")
        register_oci_profile(default)

    if default:
        field_changed = _apply_oci_cli_overrides(default)

        auth_changed = False
        if auth_override and default.authentication != auth_override:
            LOGGER.info(
                "OCI DEFAULT profile authentication override: '%s' -> '%s'",
                default.authentication,
                auth_override,
            )
            default.authentication = auth_override
            auth_changed = True

        if field_changed or auth_changed:
            _check_usable(default)

    for profile in settings.oci_configs:
        if settings.genai_compartment_id:
            profile.genai_compartment_id = settings.genai_compartment_id
        if settings.genai_region:
            profile.genai_region = settings.genai_region


async def load_oci_profiles() -> None:
    """Startup entry point: load OCI profiles from the config file."""

    profiles = parse_oci_config_file()
    for prof in profiles:
        _check_usable(prof)
        prof.server_managed = True
        register_oci_profile(prof)

    apply_env_overrides()

    if profiles:
        LOGGER.info("Loaded %d OCI profile(s) from config file", len(profiles))

    # Update client_settings to reference a valid OCI profile
    if settings.oci_configs:
        default = next(
            (p for p in settings.oci_configs if p.auth_profile.casefold() == "default"),
            None,
        )
        settings.client_settings.oci.auth_profile = (
            default.auth_profile if default else settings.oci_configs[0].auth_profile
        )

    # Auto-load GenAI models when env vars provide compartment + region
    genai_profile = next(
        (p for p in settings.oci_configs if p.usable and p.genai_compartment_id and p.genai_region),
        None,
    )
    if genai_profile:
        try:
            models = await create_genai_models(genai_profile)
            LOGGER.info("Auto-loaded %d GenAI model(s) from %s", len(models), genai_profile.auth_profile)
        except Exception:
            LOGGER.warning("Failed to auto-load GenAI models", exc_info=True)
