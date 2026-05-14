"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.oci.registry.
"""
# spell-checker: disable

from unittest.mock import patch

import pytest
from pydantic import SecretStr

from server.app.core.secrets import REVEAL_KEY
from server.app.core.settings import settings
from server.app.oci.registry import (
    _OCI_CLI_FIELD_MAP,
    _apply_oci_cli_overrides,
    apply_env_overrides,
    find_oci_profile_by_name,
    load_oci_profiles,
    register_oci_profile,
)
from server.app.oci.schemas import OciProfileConfig

MODULE = "server.app.oci.registry"

# Names of all AIO_OCI_CLI_* settings attributes for easy monkeypatching
_ALL_OCI_CLI_SETTINGS = [
    "oci_cli_auth",
    *(settings_attr for _, settings_attr, _, _ in _OCI_CLI_FIELD_MAP),
]


@pytest.fixture(autouse=True)
def _reset_oci_configs():
    """Reset settings.oci_configs and client_settings.oci.auth_profile before and after each test."""
    original = settings.oci_configs
    original_auth = settings.client_settings.oci.auth_profile
    settings.oci_configs = []
    yield
    settings.oci_configs = original
    settings.client_settings.oci.auth_profile = original_auth


@pytest.fixture()
def _clear_oci_cli_env(monkeypatch):
    """Clear all OCI_CLI_* env vars and AIO_OCI_CLI_* settings."""
    for env_var, settings_attr, _, _ in _OCI_CLI_FIELD_MAP:
        monkeypatch.delenv(env_var, raising=False)
        monkeypatch.setattr(settings, settings_attr, None)
    monkeypatch.delenv("OCI_CLI_AUTH", raising=False)
    monkeypatch.setattr(settings, "oci_cli_auth", None)
    monkeypatch.setattr(settings, "genai_compartment_id", None)
    monkeypatch.setattr(settings, "genai_region", None)


# ---------------------------------------------------------------------------
# register_oci_profile
# ---------------------------------------------------------------------------


class TestRegisterOciProfile:
    """Test register_oci_profile appending and deduplication."""

    def test_appends_new_profile(self):
        """A new profile is appended to oci_configs."""
        profile = OciProfileConfig(auth_profile="NEW")
        register_oci_profile(profile)
        assert len(settings.oci_configs) == 1
        assert settings.oci_configs[0].auth_profile == "NEW"

    def test_deduplicates_by_auth_profile_case_insensitive(self):
        """Re-registering same auth_profile (case-insensitive) replaces the earlier entry."""
        p1 = OciProfileConfig(auth_profile="TEST", tenancy="old")
        p2 = OciProfileConfig(auth_profile="test", tenancy="new")
        register_oci_profile(p1)
        register_oci_profile(p2)
        assert len(settings.oci_configs) == 1
        assert settings.oci_configs[0].tenancy == "new"


class TestFindOciProfileByName:
    """find_oci_profile_by_name must mirror the rest of the OCI stack's casing rules."""

    def test_exact_match(self):
        register_oci_profile(OciProfileConfig(auth_profile="DEFAULT"))
        assert find_oci_profile_by_name("DEFAULT") is not None

    def test_case_insensitive_match(self):
        """Client settings may persist a profile reference with different casing
        than the registered profile (config files, hand-edited DB rows). The
        lookup must succeed so cache identity and the loader resolve the same
        profile API callers see."""
        register_oci_profile(OciProfileConfig(auth_profile="DEFAULT"))
        assert find_oci_profile_by_name("default") is not None
        assert find_oci_profile_by_name("DeFaUlT") is not None

    def test_unknown_returns_none(self):
        register_oci_profile(OciProfileConfig(auth_profile="DEFAULT"))
        assert find_oci_profile_by_name("OTHER") is None

    def test_none_name_returns_none(self):
        register_oci_profile(OciProfileConfig(auth_profile="DEFAULT"))
        assert find_oci_profile_by_name(None) is None


# ---------------------------------------------------------------------------
# _apply_oci_cli_overrides
# ---------------------------------------------------------------------------


class TestApplyOciCliOverrides:
    """Test _apply_oci_cli_overrides field-level env var overrides."""

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    @pytest.mark.parametrize(
        "env_var,profile_field,value",
        [
            ("OCI_CLI_TENANCY", "tenancy", "ocid1.tenancy.oc1..env"),
            ("OCI_CLI_REGION", "region", "us-ashburn-1"),
            ("OCI_CLI_USER", "user", "ocid1.user.oc1..env"),
            ("OCI_CLI_FINGERPRINT", "fingerprint", "aa:bb:cc:dd"),
            ("OCI_CLI_KEY_FILE", "key_file", "/path/to/key.pem"),
            ("OCI_CLI_KEY_CONTENT", "key_content", "-----BEGIN RSA PRIVATE KEY-----"),
            ("OCI_CLI_PASSPHRASE", "pass_phrase", "s3cret"),
            ("OCI_CLI_SECURITY_TOKEN_FILE", "security_token_file", "/path/to/token"),
        ],
    )
    def test_env_var_overrides_profile_field(self, monkeypatch, env_var, profile_field, value):
        """Each OCI_CLI_* env var overrides the corresponding profile field."""
        from server.app.core.secrets import reveal

        profile = OciProfileConfig(auth_profile="DEFAULT")
        monkeypatch.setenv(env_var, value)

        changed = _apply_oci_cli_overrides(profile)

        assert changed is True
        assert reveal(getattr(profile, profile_field)) == value

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    @pytest.mark.parametrize(
        "settings_attr,profile_field,value",
        [
            ("oci_cli_tenancy", "tenancy", "ocid1.tenancy.oc1..aio"),
            ("oci_cli_region", "region", "eu-frankfurt-1"),
            ("oci_cli_user", "user", "ocid1.user.oc1..aio"),
            ("oci_cli_fingerprint", "fingerprint", "11:22:33:44"),
            ("oci_cli_key_file", "key_file", "/aio/key.pem"),
            ("oci_cli_key_content", "key_content", "-----BEGIN KEY-----"),
            ("oci_cli_passphrase", "pass_phrase", "aio-pass"),
            ("oci_cli_security_token_file", "security_token_file", "/aio/token"),
        ],
    )
    def test_aio_setting_overrides_profile_field(self, monkeypatch, settings_attr, profile_field, value):
        """Each AIO_OCI_CLI_* setting overrides the corresponding profile field."""
        from server.app.core.secrets import reveal

        profile = OciProfileConfig(auth_profile="DEFAULT")
        # SecretStr on Settings for the credential fields mirrors the runtime
        # shape produced by ``env_prefix`` loading.
        if settings_attr in ("oci_cli_key_content", "oci_cli_passphrase"):
            monkeypatch.setattr(settings, settings_attr, SecretStr(value))
        else:
            monkeypatch.setattr(settings, settings_attr, value)

        changed = _apply_oci_cli_overrides(profile)

        assert changed is True
        assert reveal(getattr(profile, profile_field)) == value

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_env_var_takes_precedence_over_aio_setting(self, monkeypatch):
        """OCI_CLI_* env var takes precedence over AIO_OCI_CLI_* setting."""
        profile = OciProfileConfig(auth_profile="DEFAULT")
        monkeypatch.setenv("OCI_CLI_TENANCY", "from-env")
        monkeypatch.setattr(settings, "oci_cli_tenancy", "from-aio")

        _apply_oci_cli_overrides(profile)

        assert profile.tenancy == "from-env"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_returns_false_when_no_overrides(self):
        """Returns False when no env vars or settings are set."""
        profile = OciProfileConfig(auth_profile="DEFAULT")
        assert _apply_oci_cli_overrides(profile) is False

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_returns_false_when_value_unchanged(self, monkeypatch):
        """Returns False when env var matches existing profile value."""
        profile = OciProfileConfig(auth_profile="DEFAULT", tenancy="same")
        monkeypatch.setenv("OCI_CLI_TENANCY", "same")
        assert _apply_oci_cli_overrides(profile) is False

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_key_file_expands_tilde(self, monkeypatch):
        """OCI_CLI_KEY_FILE applies os.path.expanduser."""
        profile = OciProfileConfig(auth_profile="DEFAULT")
        monkeypatch.setenv("OCI_CLI_KEY_FILE", "~/oci_key.pem")

        _apply_oci_cli_overrides(profile)

        assert isinstance(profile.key_file, str)
        assert not profile.key_file.startswith("~")
        assert profile.key_file.endswith("oci_key.pem")

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_security_token_file_expands_tilde(self, monkeypatch):
        """OCI_CLI_SECURITY_TOKEN_FILE applies os.path.expanduser."""
        profile = OciProfileConfig(auth_profile="DEFAULT")
        monkeypatch.setenv("OCI_CLI_SECURITY_TOKEN_FILE", "~/token")

        _apply_oci_cli_overrides(profile)

        assert isinstance(profile.security_token_file, str)
        assert not profile.security_token_file.startswith("~")
        assert profile.security_token_file.endswith("token")

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_key_file_override_clears_key_content(self, monkeypatch):
        """Overriding key_file clears key_content so the file-based key wins."""
        profile = OciProfileConfig(auth_profile="DEFAULT", key_content=SecretStr("embedded-key"))
        monkeypatch.setenv("OCI_CLI_KEY_FILE", "/new/key.pem")

        _apply_oci_cli_overrides(profile)

        assert profile.key_file == "/new/key.pem"
        assert profile.key_content is None

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_key_content_override_clears_key_file(self, monkeypatch):
        """Overriding key_content clears key_file so the inline key wins."""
        from server.app.core.secrets import reveal

        profile = OciProfileConfig(auth_profile="DEFAULT", key_file="/old/key.pem")
        monkeypatch.setenv("OCI_CLI_KEY_CONTENT", "-----BEGIN RSA PRIVATE KEY-----")

        _apply_oci_cli_overrides(profile)

        assert reveal(profile.key_content) == "-----BEGIN RSA PRIVATE KEY-----"
        assert profile.key_file is None

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_env_var_assignment_yields_secretstr_for_reveal_dump(self, monkeypatch):
        """OCI_CLI_* secret env vars produce SecretStr-typed profile fields
        that round-trip through ``model_dump`` in both default and reveal modes.
        """
        profile = OciProfileConfig(auth_profile="DEFAULT")
        monkeypatch.setenv("OCI_CLI_KEY_CONTENT", "-----BEGIN RSA-----")
        monkeypatch.setenv("OCI_CLI_PASSPHRASE", "phrase-from-env")

        _apply_oci_cli_overrides(profile)

        assert isinstance(profile.key_content, SecretStr)
        assert isinstance(profile.pass_phrase, SecretStr)

        dumped = profile.model_dump(mode="json", context={REVEAL_KEY: True})
        assert dumped["key_content"] == "-----BEGIN RSA-----"
        assert dumped["pass_phrase"] == "phrase-from-env"

        masked = profile.model_dump()
        assert masked["key_content"] == "**********"
        assert masked["pass_phrase"] == "**********"


# ---------------------------------------------------------------------------
# apply_env_overrides
# ---------------------------------------------------------------------------


class TestApplyEnvOverrides:
    """Test apply_env_overrides from settings to OCI profiles."""

    def test_sets_genai_compartment_id_from_settings(self, monkeypatch):
        """genai_compartment_id is applied from settings."""
        profile = OciProfileConfig(auth_profile="TEST")
        settings.oci_configs = [profile]
        monkeypatch.setattr(settings, "genai_compartment_id", "ocid1.compartment.oc1..env")
        monkeypatch.setattr(settings, "genai_region", "")

        apply_env_overrides()

        assert profile.genai_compartment_id == "ocid1.compartment.oc1..env"

    def test_sets_genai_region_from_settings(self, monkeypatch):
        """genai_region is applied from settings."""
        profile = OciProfileConfig(auth_profile="TEST")
        settings.oci_configs = [profile]
        monkeypatch.setattr(settings, "genai_compartment_id", "")
        monkeypatch.setattr(settings, "genai_region", "us-chicago-1")

        apply_env_overrides()

        assert profile.genai_region == "us-chicago-1"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_skips_when_settings_values_are_empty(self):
        """Empty settings values are not applied."""
        profile = OciProfileConfig(auth_profile="TEST", genai_compartment_id="original", genai_region="original-region")
        settings.oci_configs = [profile]

        apply_env_overrides()

        assert profile.genai_compartment_id == "original"
        assert profile.genai_region == "original-region"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_oci_cli_auth_overrides_default_profile(self, monkeypatch):
        """OCI_CLI_AUTH env var overrides the DEFAULT profile's authentication."""
        profile = OciProfileConfig(auth_profile="DEFAULT", authentication="api_key")
        settings.oci_configs = [profile]
        monkeypatch.setenv("OCI_CLI_AUTH", "instance_principal")

        with patch(f"{MODULE}._check_usable"):
            apply_env_overrides()

        assert profile.authentication == "instance_principal"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_oci_cli_auth_override_rechecks_usability(self, monkeypatch):
        """Changing authentication re-runs _check_usable on the DEFAULT profile."""
        profile = OciProfileConfig(auth_profile="DEFAULT", authentication="api_key", usable=True)
        settings.oci_configs = [profile]
        monkeypatch.setenv("OCI_CLI_AUTH", "instance_principal")

        with patch(f"{MODULE}._check_usable") as mock_check:
            apply_env_overrides()

        mock_check.assert_called_once_with(profile)

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_aio_oci_cli_auth_overrides_default_profile(self, monkeypatch):
        """AIO_OCI_CLI_AUTH setting overrides the DEFAULT profile's authentication."""
        profile = OciProfileConfig(auth_profile="DEFAULT", authentication="api_key")
        settings.oci_configs = [profile]
        monkeypatch.setattr(settings, "oci_cli_auth", "resource_principal")

        with patch(f"{MODULE}._check_usable"):
            apply_env_overrides()

        assert profile.authentication == "resource_principal"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_oci_cli_auth_env_takes_precedence_over_aio_setting(self, monkeypatch):
        """OCI_CLI_AUTH env var takes precedence over AIO_OCI_CLI_AUTH."""
        profile = OciProfileConfig(auth_profile="DEFAULT", authentication="api_key")
        settings.oci_configs = [profile]
        monkeypatch.setenv("OCI_CLI_AUTH", "instance_principal")
        monkeypatch.setattr(settings, "oci_cli_auth", "resource_principal")

        with patch(f"{MODULE}._check_usable"):
            apply_env_overrides()

        assert profile.authentication == "instance_principal"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_oci_cli_auth_creates_default_profile_if_missing(self, monkeypatch):
        """OCI_CLI_AUTH creates a DEFAULT profile when none exists."""
        monkeypatch.setenv("OCI_CLI_AUTH", "security_token")

        with patch(f"{MODULE}._check_usable"):
            apply_env_overrides()

        assert len(settings.oci_configs) == 1
        assert settings.oci_configs[0].auth_profile == "DEFAULT"
        assert settings.oci_configs[0].authentication == "security_token"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_oci_cli_auth_created_profile_checks_usability(self, monkeypatch):
        """Newly created DEFAULT profile from env var runs _check_usable."""
        monkeypatch.setenv("OCI_CLI_AUTH", "instance_principal")

        with patch(f"{MODULE}._check_usable") as mock_check:
            apply_env_overrides()

        mock_check.assert_called_once()
        assert mock_check.call_args[0][0].auth_profile == "DEFAULT"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_invalid_oci_cli_auth_is_ignored(self, monkeypatch):
        """Invalid OCI_CLI_AUTH value is ignored."""
        profile = OciProfileConfig(auth_profile="DEFAULT", authentication="api_key")
        settings.oci_configs = [profile]
        monkeypatch.setenv("OCI_CLI_AUTH", "bogus_value")

        apply_env_overrides()

        assert profile.authentication == "api_key"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_oci_cli_auth_does_not_affect_non_default_profiles(self, monkeypatch):
        """OCI_CLI_AUTH only affects the DEFAULT profile, not other profiles."""
        default = OciProfileConfig(auth_profile="DEFAULT", authentication="api_key")
        other = OciProfileConfig(auth_profile="PROD", authentication="api_key")
        settings.oci_configs = [default, other]
        monkeypatch.setenv("OCI_CLI_AUTH", "instance_principal")

        with patch(f"{MODULE}._check_usable"):
            apply_env_overrides()

        assert default.authentication == "instance_principal"
        assert other.authentication == "api_key"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_field_overrides_create_default_profile(self, monkeypatch):
        """OCI_CLI_* field env vars create a DEFAULT profile when none exists."""
        monkeypatch.setenv("OCI_CLI_TENANCY", "ocid1.tenancy.oc1..new")
        monkeypatch.setenv("OCI_CLI_REGION", "us-phoenix-1")

        with patch(f"{MODULE}._check_usable"):
            apply_env_overrides()

        assert len(settings.oci_configs) == 1
        default = settings.oci_configs[0]
        assert default.auth_profile == "DEFAULT"
        assert default.tenancy == "ocid1.tenancy.oc1..new"
        assert default.region == "us-phoenix-1"

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_field_overrides_trigger_check_usable(self, monkeypatch):
        """Field changes trigger _check_usable."""
        profile = OciProfileConfig(auth_profile="DEFAULT")
        settings.oci_configs = [profile]
        monkeypatch.setenv("OCI_CLI_REGION", "eu-frankfurt-1")

        with patch(f"{MODULE}._check_usable") as mock_check:
            apply_env_overrides()

        mock_check.assert_called_once_with(profile)

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_no_overrides_skips_check_usable(self):
        """No env vars set means _check_usable is not called."""
        profile = OciProfileConfig(auth_profile="DEFAULT")
        settings.oci_configs = [profile]

        with patch(f"{MODULE}._check_usable") as mock_check:
            apply_env_overrides()

        mock_check.assert_not_called()

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_combined_field_and_auth_override_calls_check_usable_once(self, monkeypatch):
        """Both field and auth changes result in a single _check_usable call."""
        profile = OciProfileConfig(auth_profile="DEFAULT", authentication="api_key")
        settings.oci_configs = [profile]
        monkeypatch.setenv("OCI_CLI_REGION", "us-ashburn-1")
        monkeypatch.setenv("OCI_CLI_AUTH", "instance_principal")

        with patch(f"{MODULE}._check_usable") as mock_check:
            apply_env_overrides()

        mock_check.assert_called_once_with(profile)

    @pytest.mark.usefixtures("_clear_oci_cli_env")
    def test_field_overrides_do_not_affect_non_default_profiles(self, monkeypatch):
        """OCI_CLI_* field overrides only affect the DEFAULT profile."""
        default = OciProfileConfig(auth_profile="DEFAULT", tenancy="old")
        other = OciProfileConfig(auth_profile="PROD", tenancy="prod-tenancy")
        settings.oci_configs = [default, other]
        monkeypatch.setenv("OCI_CLI_TENANCY", "new-tenancy")

        with patch(f"{MODULE}._check_usable"):
            apply_env_overrides()

        assert default.tenancy == "new-tenancy"
        assert other.tenancy == "prod-tenancy"


# ---------------------------------------------------------------------------
# load_oci_profiles
# ---------------------------------------------------------------------------


class TestLoadOciProfiles:
    """Test load_oci_profiles startup function."""

    @pytest.mark.anyio
    async def test_calls_parse_check_register_env_overrides(self):
        """load_oci_profiles calls parse, check, register, and env_overrides."""
        profile = OciProfileConfig(auth_profile="FILE_PROFILE", tenancy="t")

        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]) as mock_parse,
            patch(f"{MODULE}._check_usable") as mock_check,
            patch(f"{MODULE}.register_oci_profile") as mock_register,
            patch(f"{MODULE}.apply_env_overrides") as mock_env,
        ):
            await load_oci_profiles()

        mock_parse.assert_called_once()
        mock_check.assert_called_once_with(profile)
        mock_register.assert_called_once_with(profile)
        mock_env.assert_called_once()

    @pytest.mark.anyio
    async def test_sets_server_managed_true(self):
        """Loaded profiles have server_managed=True."""
        profile = OciProfileConfig(auth_profile="FILE_PROFILE")

        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.register_oci_profile"),
            patch(f"{MODULE}.apply_env_overrides"),
        ):
            await load_oci_profiles()

        assert profile.server_managed is True

    @pytest.mark.anyio
    async def test_empty_config_file_logs_nothing(self):
        """Empty config file does not log anything."""
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[]),
            patch(f"{MODULE}.apply_env_overrides"),
            patch(f"{MODULE}.LOGGER") as mock_logger,
        ):
            await load_oci_profiles()

        mock_logger.info.assert_not_called()

    @pytest.mark.anyio
    async def test_sets_auth_profile_to_default_when_exists(self):
        """auth_profile is set to DEFAULT when a DEFAULT profile exists."""
        profiles = [
            OciProfileConfig(auth_profile="DEFAULT"),
            OciProfileConfig(auth_profile="OTHER"),
        ]
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=profiles),
            patch(f"{MODULE}._check_usable"),
        ):
            await load_oci_profiles()

        assert settings.client_settings.oci.auth_profile == "DEFAULT"

    @pytest.mark.anyio
    async def test_sets_auth_profile_to_first_when_no_default(self):
        """auth_profile is set to first profile when no DEFAULT profile exists."""
        profiles = [
            OciProfileConfig(auth_profile="PROD"),
            OciProfileConfig(auth_profile="DEV"),
        ]
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=profiles),
            patch(f"{MODULE}._check_usable"),
        ):
            await load_oci_profiles()

        assert settings.client_settings.oci.auth_profile == "PROD"

    @pytest.mark.anyio
    async def test_leaves_auth_profile_unchanged_when_no_profiles(self):
        """auth_profile stays unchanged when no profiles are loaded."""
        before = settings.client_settings.oci.auth_profile
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[]),
            patch(f"{MODULE}._check_usable"),
        ):
            await load_oci_profiles()

        assert settings.client_settings.oci.auth_profile == before


class TestLoadOciProfilesGenaiOverlay:
    """DB overlay for GenAI compartment/region applied during load_oci_profiles."""

    @pytest.mark.anyio
    async def test_overlay_applied_when_db_has_values(self, _clear_oci_cli_env):
        profile = OciProfileConfig(auth_profile="DEFAULT")
        overlay = {
            "default": {
                "genai_compartment_id": "ocid1.compartment.oc1..fromdb",
                "genai_region": "us-chicago-1",
            }
        }
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value=overlay),
        ):
            await load_oci_profiles()

        assert profile.genai_compartment_id == "ocid1.compartment.oc1..fromdb"
        assert profile.genai_region == "us-chicago-1"

    @pytest.mark.anyio
    async def test_env_var_takes_precedence_over_overlay(self, monkeypatch, _clear_oci_cli_env):
        """env > DB: env genai_compartment_id wins when both are set."""
        profile = OciProfileConfig(auth_profile="DEFAULT")
        monkeypatch.setattr(settings, "genai_compartment_id", "ocid1.compartment.oc1..fromenv")
        overlay = {"default": {"genai_compartment_id": "ocid1.compartment.oc1..fromdb", "genai_region": None}}
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value=overlay),
        ):
            await load_oci_profiles()

        assert profile.genai_compartment_id == "ocid1.compartment.oc1..fromenv"

    @pytest.mark.anyio
    async def test_overlay_null_clears_config_file_value(self, _clear_oci_cli_env):
        """Explicit null in overlay clears the field set by the config file.

        Required so that clearing GenAI fields through the UI/API is durable
        across restarts when ``~/.oci/config`` would otherwise repopulate them.
        """
        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..fromfile",
            genai_region="us-ashburn-1",
        )
        overlay = {"default": {"genai_compartment_id": None, "genai_region": None}}
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value=overlay),
        ):
            await load_oci_profiles()

        assert profile.genai_compartment_id is None
        assert profile.genai_region is None

    @pytest.mark.anyio
    async def test_overlay_with_omitted_field_preserves_file_value(self, _clear_oci_cli_env):
        """Partial overlay (only one key present) leaves the omitted field tracking the file.

        Distinct from the null-clear case: key absence means "DB has no opinion".
        """
        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..fromfile",
            genai_region="us-ashburn-1",
        )
        overlay = {"default": {"genai_region": "us-chicago-1"}}
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value=overlay),
        ):
            await load_oci_profiles()

        assert profile.genai_compartment_id == "ocid1.compartment.oc1..fromfile"
        assert profile.genai_region == "us-chicago-1"

    @pytest.mark.anyio
    async def test_overlay_null_clears_single_field_keeps_other(self, _clear_oci_cli_env):
        """Partial clear: null for compartment overrides file, region from overlay applies."""
        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..fromfile",
            genai_region="us-ashburn-1",
        )
        overlay = {"default": {"genai_compartment_id": None, "genai_region": "us-chicago-1"}}
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value=overlay),
        ):
            await load_oci_profiles()

        assert profile.genai_compartment_id is None
        assert profile.genai_region == "us-chicago-1"

    @pytest.mark.anyio
    async def test_overlay_matches_profile_case_insensitively(self, _clear_oci_cli_env):
        profile = OciProfileConfig(auth_profile="Production")
        overlay = {"production": {"genai_compartment_id": "ocid1.compartment.oc1..prod", "genai_region": None}}
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value=overlay),
        ):
            await load_oci_profiles()

        assert profile.genai_compartment_id == "ocid1.compartment.oc1..prod"

    @pytest.mark.anyio
    async def test_overlay_applies_to_env_only_default_profile(self, monkeypatch, _clear_oci_cli_env):
        """Env-only deployment: DEFAULT created by apply_env_overrides still receives the overlay."""
        monkeypatch.setattr(settings, "oci_cli_tenancy", "ocid1.tenancy.oc1..env")
        overlay = {
            "default": {
                "genai_compartment_id": "ocid1.compartment.oc1..persisted",
                "genai_region": "us-chicago-1",
            }
        }
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value=overlay),
        ):
            await load_oci_profiles()

        assert len(settings.oci_configs) == 1
        default = settings.oci_configs[0]
        assert default.auth_profile == "DEFAULT"
        assert default.genai_compartment_id == "ocid1.compartment.oc1..persisted"
        assert default.genai_region == "us-chicago-1"

    @pytest.mark.anyio
    async def test_empty_overlay_is_noop(self, _clear_oci_cli_env):
        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..fromfile",
        )
        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value={}),
        ):
            await load_oci_profiles()

        assert profile.genai_compartment_id == "ocid1.compartment.oc1..fromfile"


class TestLoadOciProfilesAutoLoadRollback:
    """Startup auto-load must not let a transient OCI failure delete previously persisted models."""

    @pytest.fixture
    def _restore_model_configs(self):
        saved = settings.model_configs[:]
        yield
        settings.model_configs = saved

    @pytest.mark.anyio
    async def test_empty_discovery_preserves_existing_oci_models(
        self, _clear_oci_cli_env, _restore_model_configs
    ):
        """Empty discovery against the same region — assume transient and preserve."""
        from server.app.models.schemas import ModelConfig

        saved_oci_model = ModelConfig(
            id="cohere.command",
            type="ll",
            provider="oci",
            api_base="https://inference.generativeai.us-chicago-1.oci.oraclecloud.com",
            enabled=True,
        )
        settings.model_configs = [saved_oci_model]

        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..cc",
            genai_region="us-chicago-1",
            usable=True,
        )

        async def _fake_create_genai_models(_profile):
            settings.model_configs = [m for m in settings.model_configs if m.provider != "oci"]
            return []

        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value={}),
            patch(f"{MODULE}.create_genai_models", side_effect=_fake_create_genai_models),
        ):
            await load_oci_profiles()

        assert saved_oci_model in settings.model_configs

    @pytest.mark.anyio
    async def test_empty_discovery_after_region_change_does_not_restore_stale(
        self, _clear_oci_cli_env, _restore_model_configs
    ):
        """Region changed → snapshot's api_base is stale → must not be restored.

        Otherwise the server keeps exposing models whose api_base points at the
        old region after the user has switched.
        """
        from server.app.models.schemas import ModelConfig

        stale_model = ModelConfig(
            id="cohere.command",
            type="ll",
            provider="oci",
            api_base="https://inference.generativeai.us-ashburn-1.oci.oraclecloud.com",
            enabled=True,
        )
        settings.model_configs = [stale_model]

        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..cc",
            genai_region="us-chicago-1",
            usable=True,
        )

        async def _fake_create_genai_models(_profile):
            settings.model_configs = [m for m in settings.model_configs if m.provider != "oci"]
            return []

        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value={}),
            patch(f"{MODULE}.create_genai_models", side_effect=_fake_create_genai_models),
        ):
            await load_oci_profiles()

        assert stale_model not in settings.model_configs

    @pytest.mark.anyio
    async def test_exception_after_region_change_does_not_restore_stale(
        self, _clear_oci_cli_env, _restore_model_configs
    ):
        """Exception path also must not restore stale models from a different region."""
        from server.app.models.schemas import ModelConfig

        stale_model = ModelConfig(
            id="cohere.command",
            type="ll",
            provider="oci",
            api_base="https://inference.generativeai.us-ashburn-1.oci.oraclecloud.com",
            enabled=True,
        )
        settings.model_configs = [stale_model]

        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..cc",
            genai_region="us-chicago-1",
            usable=True,
        )

        async def _fake_create_genai_models(_profile):
            settings.model_configs = [m for m in settings.model_configs if m.provider != "oci"]
            raise RuntimeError("OCI service unavailable")

        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value={}),
            patch(f"{MODULE}.create_genai_models", side_effect=_fake_create_genai_models),
        ):
            await load_oci_profiles()

        assert stale_model not in settings.model_configs

    @pytest.mark.anyio
    async def test_exception_during_discovery_restores_model_configs(
        self, _clear_oci_cli_env, _restore_model_configs
    ):
        """An exception against the *current* region restores the pre-call snapshot."""
        from server.app.models.schemas import ModelConfig

        saved_oci_model = ModelConfig(
            id="cohere.command",
            type="ll",
            provider="oci",
            api_base="https://inference.generativeai.us-chicago-1.oci.oraclecloud.com",
            enabled=True,
        )
        settings.model_configs = [saved_oci_model]

        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..cc",
            genai_region="us-chicago-1",
            usable=True,
        )

        async def _fake_create_genai_models(_profile):
            settings.model_configs = [m for m in settings.model_configs if m.provider != "oci"]
            raise RuntimeError("OCI service unavailable")

        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value={}),
            patch(f"{MODULE}.create_genai_models", side_effect=_fake_create_genai_models),
        ):
            await load_oci_profiles()

        assert saved_oci_model in settings.model_configs

    @pytest.mark.anyio
    async def test_successful_discovery_replaces_models(self, _clear_oci_cli_env, _restore_model_configs):
        """A successful create_genai_models() result is kept (no restore)."""
        from server.app.models.schemas import ModelConfig

        old = ModelConfig(id="old.model", type="ll", provider="oci", enabled=True)
        new = ModelConfig(id="new.model", type="ll", provider="oci", enabled=True)
        settings.model_configs = [old]

        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..cc",
            genai_region="us-chicago-1",
            usable=True,
        )

        async def _fake_create_genai_models(_profile):
            settings.model_configs = [m for m in settings.model_configs if m.provider != "oci"] + [new]
            return [new]

        with (
            patch(f"{MODULE}.parse_oci_config_file", return_value=[profile]),
            patch(f"{MODULE}._check_usable"),
            patch(f"{MODULE}.load_oci_genai_overlay", return_value={}),
            patch(f"{MODULE}.create_genai_models", side_effect=_fake_create_genai_models),
        ):
            await load_oci_profiles()

        assert new in settings.model_configs
        assert old not in settings.model_configs
