"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.oci.schemas Pydantic models.
"""
# spell-checker: disable

from typing import Any, cast

import pytest

from server.app.oci.schemas import OciProfileConfig, OciProfileUpdate, OciSensitive

# ---------------------------------------------------------------------------
# OciSensitive
# ---------------------------------------------------------------------------


class TestOciSensitive:
    """Test OciSensitive defaults."""

    def test_all_fields_default_to_none(self):
        """All sensitive fields default to None."""
        s = OciSensitive()
        assert s.fingerprint is None
        assert s.key_content is None
        assert s.pass_phrase is None
        assert s.security_token_file is None


# ---------------------------------------------------------------------------
# OciProfileConfig
# ---------------------------------------------------------------------------


class TestOciProfileConfig:
    """Test OciProfileConfig construction and defaults."""

    def test_required_auth_profile(self):
        """auth_profile is required."""
        with pytest.raises(Exception):
            cast(Any, OciProfileConfig)()

    def test_defaults(self):
        """Default values are set correctly."""
        cfg = OciProfileConfig(auth_profile="TEST")
        assert cfg.authentication == "api_key"
        assert cfg.usable is False
        assert cfg.server_managed is False

    def test_inherits_sensitive_fields(self):
        """Sensitive fields inherited from OciSensitive are accessible."""
        cfg = OciProfileConfig(
            auth_profile="TEST",
            fingerprint="aa:bb:cc",
            key_content="key-data",
            key_file="/path/to/key",
            pass_phrase="pass",
            security_token_file="/path/to/token",
        )
        assert cfg.fingerprint == "aa:bb:cc"
        assert cfg.key_content == "key-data"
        assert cfg.key_file == "/path/to/key"
        assert cfg.pass_phrase == "pass"
        assert cfg.security_token_file == "/path/to/token"

    def test_namespace_readonly_field(self):
        """namespace field has readOnly in json_schema_extra."""
        _ = OciProfileConfig(auth_profile="TEST")
        field_info = OciProfileConfig.model_fields.get("namespace")
        assert field_info is not None
        assert field_info.json_schema_extra == {"readOnly": True}


# ---------------------------------------------------------------------------
# OciProfileUpdate
# ---------------------------------------------------------------------------


class TestOciProfileUpdate:
    """Test OciProfileUpdate optional fields and validators."""

    def test_all_fields_optional(self):
        """Empty constructor succeeds with all fields None."""
        u = OciProfileUpdate()
        assert u.user is None
        assert u.authentication is None
        assert u.tenancy is None
        assert u.region is None

    def test_empty_strings_to_none(self):
        """Empty strings are converted to None by the validator."""
        u = OciProfileUpdate(tenancy="", region="us-phoenix-1", user="")
        assert u.tenancy is None
        assert u.region == "us-phoenix-1"
        assert u.user is None

    def test_model_dump_exclude_unset(self):
        """model_dump(exclude_unset=True) omits unset fields."""
        u = OciProfileUpdate(tenancy="ocid1.tenancy.oc1..test")
        dumped = u.model_dump(exclude_unset=True)
        assert dumped == {"tenancy": "ocid1.tenancy.oc1..test"}
