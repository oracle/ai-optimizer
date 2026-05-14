"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI profile registry and startup lifecycle.
"""
# spell-checker: ignore genai

import logging
import os
from typing import Optional, cast, get_args

from server.app.core.secrets import coerce_secret_str
from server.app.core.settings import settings
from server.app.database.settings import load_oci_genai_overlay

from .config import _check_usable, parse_oci_config_file
from .schemas import OciAuthType, OciProfileConfig, genai_inference_endpoint
from .service import create_genai_models

LOGGER = logging.getLogger(__name__)

# Profile fields typed ``SecretField``; raw env-var strings are wrapped
# before assignment.
_SECRET_PROFILE_FIELDS = frozenset({"key_content", "pass_phrase"})

# Mapping of OCI CLI env vars to (settings_attr, profile_field, is_sensitive).
# Precedence: OCI_CLI_* env var > AIO_OCI_CLI_* setting > config file value.
# Snapshot of file+env-derived GenAI fields per profile, captured at the end of
# ``load_oci_profiles`` before the DB overlay is applied. Keyed by casefolded
# auth_profile, the inner dict has ``genai_compartment_id`` and ``genai_region``.
# ``persist_settings`` compares against this baseline so values the user never
# edited are not written to the DB (which would otherwise mask later config-file
# changes).
_source_baseline: dict[str, dict[str, Optional[str]]] = {}


def get_oci_source_baseline() -> dict[str, dict[str, Optional[str]]]:
    """Return the file+env baseline for OCI GenAI fields. Empty until startup runs."""
    return _source_baseline


def reset_oci_source_baseline() -> None:
    """Clear the captured baseline. Used by tests to isolate state between cases."""
    _source_baseline.clear()


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


def find_oci_profile_by_name(name: Optional[str]) -> Optional[OciProfileConfig]:
    """Return the profile whose auth_profile matches *name* (case-insensitive), else None.

    Matches the casing rules used by ``register_oci_profile`` (casefold dedup)
    and the OCI API endpoints (``.lower()`` lookup) so cache identity and the
    loader resolve the same profile regardless of how the client stored it.
    """
    if name is None:
        return None
    folded = name.casefold()
    for cfg in settings.oci_configs:
        if cfg.auth_profile.casefold() == folded:
            return cfg
    return None


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
            val = os.path.expanduser(val) if isinstance(val, str) else val
        if field in _SECRET_PROFILE_FIELDS:
            val = coerce_secret_str(val)
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

    # Snapshot the file+env state per profile *before* applying the DB overlay.
    # ``persist_settings`` compares against this so values that came from the
    # config file (or env) and were never user-edited are not written back to
    # the DB — otherwise the DB overlay would mask later edits to ``~/.oci/config``.
    _source_baseline.clear()
    _source_baseline.update(
        {
            prof.auth_profile.casefold(): {
                "genai_compartment_id": prof.genai_compartment_id,
                "genai_region": prof.genai_region,
            }
            for prof in settings.oci_configs
        }
    )

    # Runs after apply_env_overrides() so an env-only DEFAULT profile (created
    # there when no OCI config file exists) is present to receive the overlay.
    # Precedence: env > DB > config file — env-supplied fields are skipped.
    # ``None`` in the overlay is authoritative (records a user clear via UI/API)
    # and overrides the config-file value; key presence — not truthiness — is
    # what signals "the DB speaks for this field".
    overlay = await load_oci_genai_overlay()
    for prof in settings.oci_configs:
        saved = overlay.get(prof.auth_profile.casefold())
        if not saved:
            continue
        if not settings.genai_compartment_id and "genai_compartment_id" in saved:
            prof.genai_compartment_id = saved["genai_compartment_id"]
        if not settings.genai_region and "genai_region" in saved:
            prof.genai_region = saved["genai_region"]

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
        # create_genai_models() purges existing provider=="oci" entries before
        # registering fresh ones, and get_genai_models() swallows transient OCI
        # errors (ServiceError, timeouts) — so an outage on the configured
        # region yields an empty list and silently deletes the OCI model
        # configs persisted on a prior run. Snapshot and restore so a transient
        # failure at startup doesn't get committed by the post-startup persist.
        # *Only* restore when the snapshot was taken against the current region
        # (api_base encodes the region) — otherwise the user changed regions
        # and the snapshot is stale, so honouring the new (possibly empty)
        # state is more correct than re-exposing models pointing at the old
        # region.
        saved_model_configs = settings.model_configs[:]
        expected_api_base = genai_inference_endpoint(genai_profile.genai_region)
        prior_oci = [m for m in saved_model_configs if m.provider == "oci"]
        snapshot_is_current = bool(prior_oci) and all(m.api_base == expected_api_base for m in prior_oci)
        try:
            models = await create_genai_models(genai_profile)
            if not models and snapshot_is_current:
                settings.model_configs = saved_model_configs
                LOGGER.warning(
                    "GenAI auto-load returned no models for %s; preserving %d previously persisted OCI model config(s)",
                    genai_profile.auth_profile,
                    len(prior_oci),
                )
            else:
                LOGGER.info("Auto-loaded %d GenAI model(s) from %s", len(models), genai_profile.auth_profile)
        except Exception:
            LOGGER.warning("Failed to auto-load GenAI models", exc_info=True)
            if snapshot_is_current:
                settings.model_configs = saved_model_configs
