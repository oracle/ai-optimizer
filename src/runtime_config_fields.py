"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Single source of truth for per-host runtime config fields.

These hold reachability state determined on the running host (a model's ``status``,
a database's ``usable``), not portable configuration. Shared by the server (which
excludes them from exports and resets them on import) and the client (which ignores
them when diffing an uploaded export against current settings), so that a no-op round
trip of an export never shows a false change. Add a new runtime-only field here once
and every consumer stays in sync.
"""

# Config section name -> the runtime-only field names within each item of that section.
RUNTIME_ONLY_FIELDS: dict[str, frozenset[str]] = {
    "model_configs": frozenset({"status"}),
    "database_configs": frozenset({"usable"}),
    "oci_configs": frozenset({"usable"}),
}

# ``.field`` path suffixes for path-based comparison (the client settings diff);
# deduplicated/sorted since the same field name can repeat across sections.
RUNTIME_FIELD_SUFFIXES: tuple[str, ...] = tuple(
    sorted({f".{field}" for fields in RUNTIME_ONLY_FIELDS.values() for field in fields})
)
