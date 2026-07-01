"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Application settings loaded from etc/configuration.json files
"""

import copy
import json
import logging
from pathlib import Path
from typing import Optional, Union

from server.app.core.paths import PROJECT_ROOT
from server.app.core.settings import SettingsBase, settings
from server.app.models.connectivity import canonical_model_id

LOGGER = logging.getLogger(__name__)

_CONFIG_FILE = PROJECT_ROOT / "server" / "etc" / "configuration.json"

# Identity key spec: a single field name, or a tuple of field names for composite keys.
_IdentitySpec = Union[str, tuple[str, ...]]

# List fields merged by identity key — existing items from higher-precedence sources win.
_LIST_FIELD_KEYS: dict[str, _IdentitySpec] = {
    "database_configs": "alias",
    "model_configs": ("provider", "id"),
    "oci_configs": "auth_profile",
}


def _field_key(item: object, field: str) -> str:
    """Case-folded identity value for one *field* of *item*.

    The model ``id`` is canonicalized first so an Ollama ``foo`` and ``foo:latest``
    share an identity (matching ``find_model`` and the registry dedupe) — otherwise
    importing one while the other is persisted would seat a second, ambiguous row.
    """
    value = getattr(item, field) or ""
    if field == "id":
        value = canonical_model_id(getattr(item, "provider", ""), value)
    return value.lower()


def _extract_key(item: object, identity_spec: _IdentitySpec) -> Union[str, tuple[str, ...]]:
    """Return a hashable, case-folded identity key for *item*."""
    if isinstance(identity_spec, str):
        return _field_key(item, identity_spec)
    return tuple(_field_key(item, field) for field in identity_spec)


def _identity_fields(identity_spec: _IdentitySpec) -> frozenset[str]:
    """Return the set of field names that make up the identity key."""
    if isinstance(identity_spec, str):
        return frozenset({identity_spec})
    return frozenset(identity_spec)


def migrate_legacy_settings(data):
    """Normalise settings payloads exported from pre-2.1 versions.

    Handles v2.0.3 → 2.1 database_configs field renames:
      - name → alias
      - user → username
    Returns a deep copy; no-op for already-current payloads. Non-dict
    inputs are returned unchanged so downstream Pydantic validation can
    surface the appropriate error (instead of raising AttributeError here).
    """
    if not isinstance(data, dict):
        return data
    migrated = copy.deepcopy(data)
    for entry in migrated.get("database_configs") or []:
        if not isinstance(entry, dict):
            continue
        if "alias" not in entry and "name" in entry:
            entry["alias"] = entry.pop("name")
        if "username" not in entry and "user" in entry:
            entry["username"] = entry.pop("user")
    return migrated


def ensure_core_alias(db_configs: list, client_settings=None, client_store: Optional[dict] = None) -> None:
    """Ensure *db_configs* contains an entry with the exact alias ``"CORE"``.

    If an entry already matches case-insensitively, its alias is normalised
    to ``"CORE"``.  Otherwise the first entry is promoted.  No-op when the
    list is empty or already contains ``"CORE"`` with correct casing.

    Any *client_settings* and *client_store* entries whose database alias
    matched the old value are updated to ``"CORE"`` so that downstream
    lookups remain valid.
    """
    if not db_configs:
        return
    # Determine which alias (if any) needs to become "CORE"
    old_alias: Optional[str] = None
    for cfg in db_configs:
        if cfg.alias == "CORE":
            return  # exact match — nothing to do
    for cfg in db_configs:
        if cfg.alias.upper() == "CORE":
            old_alias = cfg.alias
            cfg.alias = "CORE"
            break
    else:
        # No CORE variant at all — promote the first entry
        old_alias = db_configs[0].alias
        db_configs[0].alias = "CORE"
    # Sync client aliases that still reference the old name
    if client_settings is not None and client_settings.database.alias == old_alias:
        client_settings.database.alias = "CORE"
    for cs in (client_store or {}).values():
        if cs.database.alias == old_alias:
            cs.database.alias = "CORE"


def load_config_file(path: Optional[Path] = None) -> Optional[SettingsBase]:
    """Load and validate configuration.json.

    Returns a SettingsBase instance on success, or None if the file is
    missing, unreadable, or contains invalid data.
    """
    config_path = path or _CONFIG_FILE
    if not config_path.is_file():
        LOGGER.info("Configuration file not found: %s", config_path)
        return None

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = migrate_legacy_settings(json.loads(raw))
        return SettingsBase.model_validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        LOGGER.warning("Failed to load configuration file %s: %s", config_path, exc)
        return None


def apply_overlay(
    source: SettingsBase,
    protected: set[str],
    exclude_fields: Optional[set[str]] = None,
) -> set[str]:
    """Overlay *source* fields onto the global ``settings`` singleton.

    Scalar fields are only applied when the field name is NOT in *protected*.
    List fields (database_configs, model_configs, oci_configs) are
    always merged by identity key; existing items win entirely.
    Fields in *exclude_fields* are skipped entirely.

    Returns the updated protected set (input | source.model_fields_set).
    """
    skip = exclude_fields or set()
    for field_name in source.model_fields_set:
        if field_name in skip:
            continue
        if field_name in _LIST_FIELD_KEYS:
            _merge_list_field(field_name, source, _LIST_FIELD_KEYS[field_name])
        elif field_name not in protected:
            value = getattr(source, field_name)
            setattr(settings, field_name, value)
            if field_name == "api_key":
                object.__setattr__(settings, "_api_key_generated", False)

    return protected | source.model_fields_set


def upsert_list_field(field_name: str, incoming: list) -> tuple[list, list]:
    """Upsert *incoming* items into ``settings.<field_name>`` by identity key.

    Unlike ``_merge_list_field`` (existing wins / additive only), this uses
    **incoming wins** semantics: matching items are updated in-place and
    new items are appended.

    Returns (created, updated) lists of items that were affected.
    """
    identity_spec = _LIST_FIELD_KEYS[field_name]
    id_fields = _identity_fields(identity_spec)
    existing_list: list = getattr(settings, field_name)
    existing_by_key = {_extract_key(item, identity_spec): item for item in existing_list}

    created, updated = [], []
    for item in incoming:
        key = _extract_key(item, identity_spec)
        target = existing_by_key.get(key)
        if target is not None:
            for fn in item.model_fields_set:
                if fn not in id_fields:
                    setattr(target, fn, getattr(item, fn))
            updated.append(target)
        else:
            existing_list.append(item)
            existing_by_key[key] = item
            created.append(item)

    return created, updated


def _merge_list_field(field_name: str, source: SettingsBase, identity_spec: _IdentitySpec) -> None:
    """Append items from *source* whose identity key is not already present."""
    existing: list = getattr(settings, field_name)
    incoming: list = getattr(source, field_name)

    existing_keys: set = {_extract_key(item, identity_spec) for item in existing}

    merged = list(existing)
    for item in incoming:
        key = _extract_key(item, identity_spec)
        if key not in existing_keys:
            merged.append(item)
            existing_keys.add(key)

    setattr(settings, field_name, merged)
