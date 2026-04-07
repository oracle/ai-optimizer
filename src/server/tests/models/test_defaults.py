"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.models.defaults constants.
"""
# spell-checker: disable

from server.app.models.defaults import ENV_OVERRIDES, FACTORY_MODELS

# ---------------------------------------------------------------------------
# FACTORY_MODELS
# ---------------------------------------------------------------------------


class TestFactoryModels:
    """Validate the built-in FACTORY_MODELS list."""

    def test_non_empty(self):
        """FACTORY_MODELS must contain at least one entry."""
        assert len(FACTORY_MODELS) > 0

    def test_required_keys_present(self):
        """Every entry must have id, type, and provider."""
        for entry in FACTORY_MODELS:
            assert "id" in entry, f"Missing 'id' in {entry}"
            assert "type" in entry, f"Missing 'type' in {entry}"
            assert "provider" in entry, f"Missing 'provider' in {entry}"

    def test_types_are_valid(self):
        """All type values must be in the allowed set."""
        allowed = {"ll", "embed", "rerank"}
        for entry in FACTORY_MODELS:
            assert entry["type"] in allowed, f"Invalid type {entry['type']!r} for {entry['id']}"

    def test_no_duplicate_id_provider_pairs(self):
        """No two entries share the same (id, provider) combination."""
        seen = set()
        for entry in FACTORY_MODELS:
            key = (entry["id"], entry["provider"])
            assert key not in seen, f"Duplicate (id, provider): {key}"
            seen.add(key)

    def test_all_disabled_by_default(self):
        """Every factory model must have enabled=False."""
        for entry in FACTORY_MODELS:
            assert entry.get("enabled") is False, f"Model {entry['id']} should be disabled"

    def test_contains_ll_and_embed_types(self):
        """FACTORY_MODELS should include both 'll' and 'embed' types."""
        types = {entry["type"] for entry in FACTORY_MODELS}
        assert "ll" in types
        assert "embed" in types

    def test_known_providers_present(self):
        """Well-known providers should be represented."""
        providers = {entry["provider"] for entry in FACTORY_MODELS}
        assert "openai" in providers
        assert "cohere" in providers


# ---------------------------------------------------------------------------
# ENV_OVERRIDES
# ---------------------------------------------------------------------------


class TestEnvOverrides:
    """Validate the ENV_OVERRIDES mapping."""

    def test_non_empty(self):
        """ENV_OVERRIDES must contain at least one entry."""
        assert len(ENV_OVERRIDES) > 0

    def test_entries_are_three_tuples_of_strings(self):
        """Each entry should be a 3-tuple of strings."""
        for entry in ENV_OVERRIDES:
            assert len(entry) == 3, f"Expected 3-tuple, got {entry}"
            env_var, provider, field = entry
            assert isinstance(env_var, str)
            assert isinstance(provider, str)
            assert isinstance(field, str)

    def test_known_entries_present(self):
        """Expected environment variable mappings should exist."""
        env_vars = {entry[0] for entry in ENV_OVERRIDES}
        assert "OPENAI_API_KEY" in env_vars
        assert "COHERE_API_KEY" in env_vars

    def test_fields_are_api_key_or_api_base(self):
        """Override fields should only be api_key or api_base."""
        for entry in ENV_OVERRIDES:
            assert entry[2] in {"api_key", "api_base"}, f"Unexpected field {entry[2]!r} for {entry[0]}"
