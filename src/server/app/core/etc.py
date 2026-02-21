"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Application settings loaded from etc/configuration.json files
"""

import json
import logging
from pathlib import Path
from typing import Optional

from server.app.core.paths import PROJECT_ROOT
from server.app.core.settings import SettingsBase, settings

LOGGER = logging.getLogger(__name__)

_CONFIG_FILE = PROJECT_ROOT / "server" / "etc" / "configuration.json"

# List fields merged by identity key — existing items from higher-precedence sources win.
_LIST_FIELD_KEYS: dict[str, str] = {
    "database_configs": "alias",
    "model_configs": "id",
    "oci_profile_configs": "auth_profile",
}


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
        data = json.loads(raw)
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
    List fields (database_configs, model_configs, oci_profile_configs) are
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


def _merge_list_field(field_name: str, source: SettingsBase, identity_key: str) -> None:
    """Append items from *source* whose identity key is not already present."""
    existing: list = getattr(settings, field_name)
    incoming: list = getattr(source, field_name)

    existing_keys: set[str] = {getattr(item, identity_key) for item in existing}

    merged = list(existing)
    for item in incoming:
        key = getattr(item, identity_key)
        if key not in existing_keys:
            merged.append(item)
            existing_keys.add(key)

    setattr(settings, field_name, merged)
