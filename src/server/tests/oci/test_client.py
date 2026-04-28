"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.oci.client.
"""
# spell-checker: disable

from unittest.mock import MagicMock, mock_open, patch

from pydantic import SecretStr

from server.app.oci.client import get_signer, init_client
from server.app.oci.schemas import OciProfileConfig

MODULE = "server.app.oci.client"


# ---------------------------------------------------------------------------
# get_signer
# ---------------------------------------------------------------------------


class TestGetSigner:
    """Test get_signer returns correct signer based on authentication type."""

    def test_instance_principal_returns_signer(self):
        """instance_principal auth type returns InstancePrincipalsSecurityTokenSigner."""
        profile = OciProfileConfig(auth_profile="TEST", authentication="instance_principal")
        mock_signer = MagicMock()

        with patch(f"{MODULE}.oci.auth.signers.InstancePrincipalsSecurityTokenSigner", return_value=mock_signer):
            result = get_signer(profile)

        assert result is mock_signer

    def test_oke_workload_identity_returns_signer(self):
        """oke_workload_identity auth type returns OKE workload identity signer."""
        profile = OciProfileConfig(auth_profile="TEST", authentication="oke_workload_identity")
        mock_signer = MagicMock()

        with patch(
            f"{MODULE}.oci.auth.signers.get_oke_workload_identity_resource_principal_signer",
            return_value=mock_signer,
        ):
            result = get_signer(profile)

        assert result is mock_signer

    def test_resource_principal_returns_signer(self):
        """resource_principal auth type returns resource principals signer."""
        profile = OciProfileConfig(auth_profile="TEST", authentication="resource_principal")
        mock_signer = MagicMock()

        with patch(f"{MODULE}.oci.auth.signers.get_resource_principals_signer", return_value=mock_signer):
            result = get_signer(profile)

        assert result is mock_signer

    def test_api_key_returns_none(self):
        """api_key auth type returns None."""
        profile = OciProfileConfig(auth_profile="TEST", authentication="api_key")
        result = get_signer(profile)
        assert result is None


# ---------------------------------------------------------------------------
# init_client
# ---------------------------------------------------------------------------


class TestInitClient:
    """Test init_client factory function."""

    def test_genai_client_with_compartment_and_region_sets_endpoint(self):
        """GenAI client with compartment and region sets service_endpoint."""
        profile = OciProfileConfig(
            auth_profile="TEST",
            genai_compartment_id="ocid1.compartment.oc1..genai",
            genai_region="us-chicago-1",
            user="u",
            fingerprint="f",
            tenancy="t",
            region="r",
            key_file="/path/key",
        )

        # Create a sentinel that is identity-equal to the real GenAI class
        mock_client_type = MagicMock()
        with (
            patch(f"{MODULE}.oci.generative_ai_inference.GenerativeAiInferenceClient", mock_client_type),
            patch(f"{MODULE}.get_signer", return_value=None),
        ):
            init_client(mock_client_type, profile)

        _, kwargs = mock_client_type.call_args
        assert kwargs["service_endpoint"] == "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com"

    def test_signer_path_returns_client_with_signer(self):
        """When get_signer returns a signer, client is created with signer."""
        profile = OciProfileConfig(auth_profile="TEST", region="us-phoenix-1")
        mock_signer = MagicMock()
        mock_client_type = MagicMock()

        with patch(f"{MODULE}.get_signer", return_value=mock_signer):
            init_client(mock_client_type, profile)

        mock_client_type.assert_called_once()
        _, kwargs = mock_client_type.call_args
        assert kwargs.get("signer") is mock_signer
        assert mock_client_type.call_args[1].get("signer") is mock_signer

    def test_security_token_path_reads_file_and_creates_signer(self):
        """security_token auth reads token file and creates SecurityTokenSigner."""
        profile = OciProfileConfig(
            auth_profile="TEST",
            authentication="security_token",
            security_token_file="/path/to/token",
            key_file="/path/to/key",
            region="us-phoenix-1",
        )
        mock_client_type = MagicMock()
        mock_private_key = MagicMock()
        mock_sec_signer = MagicMock()

        with (
            patch(f"{MODULE}.get_signer", return_value=None),
            patch("builtins.open", mock_open(read_data="token-data")),
            patch(f"{MODULE}.oci.signer.load_private_key_from_file", return_value=mock_private_key),
            patch(f"{MODULE}.oci.auth.signers.SecurityTokenSigner", return_value=mock_sec_signer),
        ):
            init_client(mock_client_type, profile)

        mock_client_type.assert_called_once()
        _, kwargs = mock_client_type.call_args
        assert kwargs.get("signer") is mock_sec_signer

    def test_api_key_path_builds_config_dict(self):
        """api_key auth builds config dict and passes to client."""
        profile = OciProfileConfig(
            auth_profile="TEST",
            authentication="api_key",
            user="ocid1.user.oc1..test",
            fingerprint="aa:bb:cc",
            tenancy="ocid1.tenancy.oc1..test",
            region="us-phoenix-1",
            key_file="/path/to/key",
        )
        mock_client_type = MagicMock()

        with patch(f"{MODULE}.get_signer", return_value=None):
            init_client(mock_client_type, profile)

        mock_client_type.assert_called_once()
        config_dict = mock_client_type.call_args[0][0]
        assert config_dict["user"] == "ocid1.user.oc1..test"
        assert config_dict["fingerprint"] == "aa:bb:cc"
        assert config_dict["tenancy"] == "ocid1.tenancy.oc1..test"
        assert config_dict["key_file"] == "/path/to/key"

    def test_key_content_used_when_key_file_absent(self):
        """key_content is used in config dict when key_file is absent."""
        profile = OciProfileConfig(
            auth_profile="TEST",
            authentication="api_key",
            user="u",
            fingerprint="f",
            tenancy="t",
            region="r",
            key_content=SecretStr("raw-key-data"),
            key_file=None,
        )
        mock_client_type = MagicMock()

        with patch(f"{MODULE}.get_signer", return_value=None):
            init_client(mock_client_type, profile)

        config_dict = mock_client_type.call_args[0][0]
        assert config_dict["key_content"] == "raw-key-data"
        assert "key_file" not in config_dict
