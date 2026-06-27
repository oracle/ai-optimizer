"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Persist and load application settings from the aio_settings table.
"""
# spell-checker: ignore systimestamp

import json
import logging
from collections.abc import Iterable, Mapping
from typing import Optional

import oracledb

from server.app.core.schemas import ClientSettings
from server.app.core.secrets import REVEAL_KEY
from server.app.core.settings import _PROTECTED_CLIENTS, SettingsBase, settings
from server.app.oci.schemas import GENAI_OVERLAY_FIELDS

from .config import get_core_pool
from .sql import execute_sql

LOGGER = logging.getLogger(__name__)


def hide_managed_db_configs(data: dict) -> None:
    """Strip DDS-managed (runtime-only) connections from a serialized settings ``data`` dict.

    Managed configs are never persisted or returned to clients; this is the single place that
    enforces that on a serialized ``database_configs`` payload (in-place).
    """
    data["database_configs"] = [c for c in data.get("database_configs", []) if not c.get("managed_by")]


# Dedicated key for the sparse OCI GenAI delta overlay; keeps the persisted
# payload from colliding with ``SettingsBase.oci_configs`` (which describes full
# profiles populated from the filesystem at startup).
_OCI_OVERLAY_KEY = "oci_genai_overlay"

_UPSERT_SQL = """
MERGE INTO aio_settings dst
USING (SELECT :client AS client FROM DUAL) src
ON (dst.client = src.client)
WHEN MATCHED THEN
    UPDATE SET settings = :settings, updated = SYSTIMESTAMP, is_current = :is_current
WHEN NOT MATCHED THEN
    INSERT (client, settings, created, updated, is_current)
    VALUES (:client, :settings, SYSTIMESTAMP, SYSTIMESTAMP, :is_current)
"""

_SELECT_SQL = """
SELECT settings FROM aio_settings WHERE client = :client
"""

_ROW_EXISTS_SQL = """
SELECT 1 FROM aio_settings WHERE client = :client
"""

_DELETE_SQL = """
DELETE FROM aio_settings WHERE client = :client
"""


async def _upsert_settings_row(
    pool: oracledb.AsyncConnectionPool, client: str, payload: dict, is_current: bool, *, label: str
) -> bool:
    """Upsert *payload* into aio_settings for *client*.

    Returns ``True`` on success, ``False`` when the write fails. *label* prefixes the
    log lines so callers stay distinguishable. Assumes *pool* is non-None (callers
    handle the unavailable-CORE best-effort case before calling).
    """
    try:
        async with pool.acquire() as conn:
            await execute_sql(
                conn,
                _UPSERT_SQL,
                {"client": client, "settings": payload, "is_current": 1 if is_current else 0},
                input_sizes={"settings": oracledb.DB_TYPE_JSON},
            )
            await conn.commit()
        LOGGER.info("%s persisted to aio_settings (client=%s)", label, client)
        return True
    except Exception as exc:
        LOGGER.error("%s: failed to persist for client=%s: %s", label, client, exc)
        return False


async def persist_settings(
    client: str = "CONFIGURED",
    is_current: bool = True,
    *,
    oci_user_touched: Optional[Mapping[str, Iterable[str]]] = None,
) -> bool:
    """Serialize current settings and upsert into aio_settings.

    Returns ``True`` on success or when the CORE pool is unavailable
    (best-effort — the in-memory change is kept).  Returns ``False``
    only when a pool exists and the write fails.

    ``oci_user_touched`` maps an OCI auth_profile (case-insensitive) to the set
    of GenAI fields the caller just explicitly changed. When a touched field's
    current value equals the file/env baseline, persist treats it as a *revert*
    and removes the override from the row instead of carrying the prior value
    forward.
    """
    pool = get_core_pool()
    if not pool:
        LOGGER.warning("persist_settings: CORE database not available — skipping")
        return True

    payload = SettingsBase.model_validate(settings).model_dump(
        mode="json",
        context={REVEAL_KEY: True},
        exclude={"oci_configs", "client_settings"},
    )
    # Backstop invariant: DDS-managed connections are runtime-only. Strip them from the
    # serialized payload so they can never be persisted, regardless of caller.
    hide_managed_db_configs(payload)
    # Only the GenAI overlay fields are persisted (auth material lives in
    # ~/.oci/config); each entry stores *deltas* from the file+env baseline so
    # later edits to ~/.oci/config take effect on the next restart. Fields
    # masked by ``AIO_GENAI_*`` env are carried forward unchanged because the
    # baseline is transient and would otherwise wipe the prior user edit.
    from server.app.oci.registry import get_oci_source_baseline  # noqa: PLC0415 — avoids circular import

    baseline = get_oci_source_baseline()
    prior_raw = await _load_raw_settings(client, op="persist_settings:carry-forward") or {}
    prior_entries = prior_raw.get(_OCI_OVERLAY_KEY) or prior_raw.get("oci_configs") or []
    prior_overlay: dict[str, dict] = {}
    for prior_entry in prior_entries:
        prior_name = prior_entry.get("auth_profile")
        if not prior_name:
            continue
        prior_overlay[prior_name.casefold()] = {
            field: prior_entry[field] for field in GENAI_OVERLAY_FIELDS if field in prior_entry
        }
    touched_map: dict[str, frozenset[str]] = {
        key.casefold(): frozenset(fields) for key, fields in (oci_user_touched or {}).items()
    }
    # When ``AIO_GENAI_*`` env masks a field, baseline reflects env — not file —
    # so we cannot tell whether the prior overlay is redundant; preserve it.
    env_masking = {field: bool(getattr(settings, field)) for field in GENAI_OVERLAY_FIELDS}

    oci_entries: list[dict] = []
    for p in settings.oci_configs:
        key = p.auth_profile.casefold()
        base = baseline.get(key, {})
        carry = prior_overlay.get(key, {})
        touched = touched_map.get(key, frozenset())
        entry: dict = {"auth_profile": p.auth_profile}
        for field in GENAI_OVERLAY_FIELDS:
            current = getattr(p, field)
            base_value = base.get(field)
            if current != base_value:
                entry[field] = current
            elif field not in touched and field in carry and (
                env_masking[field] or carry[field] != base_value
            ):
                entry[field] = carry[field]
        if len(entry) > 1:
            oci_entries.append(entry)
    payload[_OCI_OVERLAY_KEY] = oci_entries

    return await _upsert_settings_row(pool, client, payload, is_current, label="Settings")


async def _load_raw_settings(client: str, *, op: str) -> Optional[dict]:
    """Fetch and decode the JSON payload for *client*; returns None if unavailable or absent."""
    pool = get_core_pool()
    if not pool:
        LOGGER.info("%s: CORE database not available — skipping", op)
        return None

    try:
        async with pool.acquire() as conn:
            rows = await execute_sql(conn, _SELECT_SQL, {"client": client})
        if not rows:
            LOGGER.info("%s: No persisted settings found for client=%s", op, client)
            return None
        raw = rows[0][0]
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        LOGGER.warning("%s: Failed to load for client=%s: %s", op, client, exc)
        return None
    if not isinstance(data, dict):
        # JSON column can hold arrays/scalars too; callers do mapping ops on
        # the result, so a malformed row must be treated as "no settings"
        # rather than letting an AttributeError escape startup.
        LOGGER.warning(
            "%s: persisted payload for client=%s is not a JSON object (got %s)",
            op,
            client,
            type(data).__name__,
        )
        return None
    return data


async def load_settings(client: str = "CONFIGURED") -> Optional[SettingsBase]:
    """Load settings from aio_settings for the given client.

    Strips the OCI GenAI overlay keys before validating so generic callers
    (e.g. ``POST /settings``) don't surface delta-only entries as fake
    ``OciProfileConfig`` objects; ``load_oci_genai_overlay()`` reads the
    overlay directly.
    """
    data = await _load_raw_settings(client, op="load_settings")
    if data is None:
        return None
    data.pop(_OCI_OVERLAY_KEY, None)
    data.pop("oci_configs", None)
    try:
        return SettingsBase.model_validate(data)
    except Exception as exc:
        LOGGER.warning("load_settings: Failed to validate for client=%s: %s", client, exc)
        return None


async def load_client_settings(client: str = "CONFIGURED") -> Optional[ClientSettings]:
    """Load client settings from aio_settings for the given client."""
    data = await _load_raw_settings(client, op="load_client_settings")
    if data is None:
        return None
    cs_data = data.get("client_settings")
    if cs_data is None:
        return None
    try:
        return ClientSettings.model_validate(cs_data)
    except Exception as exc:
        LOGGER.warning("load_client_settings: Failed to validate for client=%s: %s", client, exc)
        return None


async def load_oci_genai_overlay(client: str = "CONFIGURED") -> dict[str, dict]:
    """Load persisted OCI GenAI overlay (compartment/region) keyed by casefolded auth_profile.

    Preserves the distinction between *omitted* keys (DB has no opinion — keep
    the file/env value) and *explicit null* (user cleared the field — override
    the file value). ``persist_settings`` only writes fields that differ from
    the file+env baseline, so faithfully echoing key-presence is required.
    """
    data = await _load_raw_settings(client, op="load_oci_genai_overlay")
    if data is None:
        return {}
    overlay: dict[str, dict] = {}
    # Read the dedicated overlay key first; fall back to the historical
    # ``oci_configs`` slot for rows persisted before the rename.
    entries = data.get(_OCI_OVERLAY_KEY) or data.get("oci_configs") or []
    for entry in entries:
        profile = entry.get("auth_profile")
        if not profile:
            continue
        overlay[profile.casefold()] = {
            field: entry[field]
            for field in ("genai_compartment_id", "genai_region")
            if field in entry
        }
    return overlay


async def row_exists(client: str) -> bool:
    """Check whether a row exists in aio_settings for the given client."""
    pool = get_core_pool()
    if not pool:
        return False

    try:
        async with pool.acquire() as conn:
            rows = await execute_sql(conn, _ROW_EXISTS_SQL, {"client": client})
        return bool(rows)
    except Exception:
        return False


async def persist_client_settings(client: str, cs: ClientSettings, is_current: bool = False) -> bool:
    """Serialize a ClientSettings object and upsert into aio_settings.

    Returns ``True`` on success or when the CORE pool is unavailable
    (best-effort — the in-memory change is kept).  Returns ``False``
    only when a pool exists and the write fails.
    """
    pool = get_core_pool()
    if not pool:
        LOGGER.warning("persist_client_settings: CORE database not available — skipping")
        return True

    # deep_data_security is runtime/session-scoped — never persisted.
    payload = {
        "client_settings": cs.model_dump(mode="json", context={REVEAL_KEY: True}, exclude={"deep_data_security"})
    }

    return await _upsert_settings_row(pool, client, payload, is_current, label="Client settings")


async def delete_row(client: str) -> None:
    """Delete a row from aio_settings. Refuses to delete FACTORY or server."""
    if client in _PROTECTED_CLIENTS:
        LOGGER.warning("delete_row: Refusing to delete %s row", client)
        return

    pool = get_core_pool()
    if not pool:
        LOGGER.warning("delete_row: CORE database not available — skipping")
        return

    try:
        async with pool.acquire() as conn:
            await execute_sql(conn, _DELETE_SQL, {"client": client})
            await conn.commit()
        LOGGER.info("Deleted aio_settings row for client=%s", client)
    except Exception as exc:
        LOGGER.warning("delete_row: Failed to delete for client=%s: %s", client, exc)
