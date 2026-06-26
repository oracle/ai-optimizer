"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the shared runtime-only config field contract.
"""

from runtime_config_fields import RUNTIME_FIELD_SUFFIXES, RUNTIME_ONLY_FIELDS


def test_runtime_field_contract():
    """The known runtime-only fields per section."""
    actual = dict(RUNTIME_ONLY_FIELDS)
    assert actual == {
        "model_configs": frozenset({"status"}),
        "database_configs": frozenset({"usable"}),
        "oci_configs": frozenset({"usable"}),
    }


def test_suffixes_stay_derived_from_fields():
    """RUNTIME_FIELD_SUFFIXES is a ``.field`` view of RUNTIME_ONLY_FIELDS — the two can't drift."""
    expected = {f".{field}" for fields in RUNTIME_ONLY_FIELDS.values() for field in fields}
    assert set(RUNTIME_FIELD_SUFFIXES) == expected == {".status", ".usable"}
