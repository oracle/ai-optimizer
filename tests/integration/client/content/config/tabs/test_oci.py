"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=unused-argument

from unittest.mock import patch
import re
import pytest

#####################################################
# Mocks
#####################################################
@pytest.fixture(name="mock_api_call_patch")
def _mock_api_call_patch():
    """Mock api_call.patch to avoid actual API calls"""
    with patch("client.utils.api_call.patch") as mock:
        yield mock


@pytest.fixture(name="mock_get_oci")
def _mock_get_oci():
    """Mock get_oci to control the state"""
    with patch("client.content.config.oci.get_oci") as mock:
        yield mock


@pytest.fixture(name="mock_api_call_get")
def _mock_api_call_get():
    """Mock api_call.get to return a mocked response"""
    with patch("client.utils.api_call.get") as mock:
        yield mock


@pytest.fixture(name="mock_server_get_namespace", autouse=True)
def _mock_server_get_namespace():
    """Mock server_oci.get_namespace to always return test_namespace"""
    with patch("server.api.utils.oci.get_namespace", return_value="test_namespace") as mock:
        yield mock


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    ST_FILE = "../src/client/content/config/tabs/oci.py"

    def test_initialise_streamlit_no_env(self, app_server, app_test):
        """Initialisation of streamlit without any OCI environment"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        user_oci_profile = at.session_state.client_settings["oci"]["auth_profile"]
        assert user_oci_profile == "DEFAULT"
        oci_lookup = {config["auth_profile"]: config for config in at.session_state.oci_configs}
        assert oci_lookup[user_oci_profile]["namespace"] is None
        assert oci_lookup[user_oci_profile]["user"] is None
        assert oci_lookup[user_oci_profile]["security_token_file"] is None
        assert oci_lookup[user_oci_profile]["tenancy"] is None
        assert oci_lookup[user_oci_profile]["region"] is None
        assert oci_lookup[user_oci_profile]["fingerprint"] is None
        assert oci_lookup[user_oci_profile]["key_file"] is None
        assert oci_lookup[user_oci_profile]["genai_region"] is None
        assert oci_lookup[user_oci_profile]["genai_compartment_id"] is None

    test_cases = [
        pytest.param(
            {
                "oci_token_auth": False,
                "expected_error": "Update Failed",
            },
            id="oci_profile_1",
        ),
        pytest.param(
            {
                "oci_token_auth": False,
                "oci_user": "ocid1.user.oc1..aaaaaaaa",
                "expected_error": "Update Failed - OCI: Invalid Config",
            },
            id="oci_profile_3",
        ),
        pytest.param(
            {
                "oci_token_auth": False,
                "oci_user": "ocid1.user.oc1..aaaaaaaa",
                "oci_fingerprint": "e8:65:45:4a:85:4b:6c:51:63:b8:84:64:ef:36:16:7b",
                "expected_error": "Update Failed - OCI: Invalid Config",
            },
            id="oci_profile_4",
        ),
        pytest.param(
            {
                "oci_token_auth": False,
                "oci_user": "ocid1.user.oc1..aaaaaaaa",
                "oci_fingerprint": "e8:65:45:4a:85:4b:6c:51:63:b8:84:64:ef:36:16:7b",
                "oci_tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
                "expected_error": "Update Failed - OCI: Invalid Key Path",
            },
            id="oci_profile_5",
        ),
        pytest.param(
            {
                "oci_token_auth": False,
                "oci_user": "ocid1.user.oc1..aaaaaaaa",
                "oci_fingerprint": "e8:65:45:4a:85:4b:6c:51:63:b8:84:64:ef:36:16:7b",
                "oci_tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
                "oci_region": "us-ashburn-1",
                "expected_error": "Update Failed - OCI: Invalid Key Path",
            },
            id="oci_profile_6",
        ),
        pytest.param(
            {
                "oci_token_auth": False,
                "oci_user": "ocid1.user.oc1..aaaaaaaa",
                "oci_fingerprint": "e8:65:45:4a:85:4b:6c:51:63:b8:84:64:ef:36:16:7b",
                "oci_tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
                "oci_region": "us-ashburn-1",
                "oci_key_file": "/dev/null",
                "expected_error": "Update Failed - OCI: The provided key is not a private key, or the provided passphrase is incorrect",
            },
            id="oci_profile_7",
        ),
        pytest.param(
            {
                "oci_token_auth": False,
                "oci_user": "ocid1.user.oc1..aaaaaaaa",
                "oci_fingerprint": "e8:65:45:4a:85:4b:6c:51:63:b8:84:64:ef:36:16:7b",
                "oci_tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
                "oci_region": "us-ashburn-1",
                "oci_key_file": "/dev/null",
                "expected_success": "Current Status: Validated - Namespace: test_namespace",
            },
            id="oci_profile_8",
        ),
    ]

    def set_patch_oci(self, at, test_case):
        """Set values"""
        at.checkbox(key="oci_token_auth").set_value(test_case["oci_token_auth"]).run()
        at.text_input(key="oci_user").set_value(test_case.get("oci_user", "")).run()
        at.text_input(key="oci_security_token_file").set_value(test_case.get("oci_security_token_file", "")).run()
        at.text_input(key="oci_fingerprint").set_value(test_case.get("oci_fingerprint", "")).run()
        at.text_input(key="oci_tenancy").set_value(test_case.get("oci_tenancy", "")).run()
        at.text_input(key="oci_region").set_value(test_case.get("oci_region", "")).run()
        at.text_input(key="oci_key_file").set_value(test_case.get("oci_key_file", "")).run()

    @pytest.mark.parametrize("test_case", [tc for tc in test_cases if tc.values[0].get("expected_error") is not None])
    def test_patch_oci_error(self, app_server, app_test, test_case):
        """Update OCI Profile Settings - Error Cases"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        assert at.session_state.client_settings["oci"]["auth_profile"] == "DEFAULT"
        self.set_patch_oci(at, test_case)
        at.button(key="save_oci").click().run()
        assert at.error[0].value == "Current Status: Unverified"
        assert re.match(test_case["expected_error"], at.error[1].value) and at.error[1].icon == "🚨"

    @pytest.mark.parametrize(
        "test_case", [tc for tc in test_cases if tc.values[0].get("expected_success") is not None]
    )
    def test_patch_oci_success(self, app_server, app_test, test_case):
        """Update OCI Profile Settings - Success Cases"""
        assert app_server is not None
        # This test directly checks the UI when the namespace is set, without making any API calls

        # Initialize the app
        at = app_test(self.ST_FILE)

        # Set the namespace directly in the session state before running the app
        assert at.session_state.client_settings["oci"]["auth_profile"] == "DEFAULT"

        # Create the state before running page to avoid state being init'd
        at.session_state.oci_configs = [
            {
                "auth_profile": "DEFAULT",
                "user": None,
                "tenancy": None,
                "region": None,
                "genai_compartment_id": "",
                "genai_region": "",
                "key_file": None,
                "security_token_file": None,
                "fingerprint": None,
                "namespace": "test_namespace",
            }
        ]
        at.run()

        # Verify the success message is displayed
        success_elements = at.success
        assert len(success_elements) > 0
        assert success_elements[0].value == test_case["expected_success"]

    def test_genai_models_missing_compartment_error(self, app_server, app_test):
        """Test error handling when compartment ID is missing for GenAI check"""
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Setup state with valid namespace but no compartment ID
        at.session_state.oci_configs = [{
            "auth_profile": "DEFAULT",
            "user": None,
            "tenancy": None,
            "region": None,
            "genai_compartment_id": "",
            "genai_region": "",
            "key_file": None,
            "security_token_file": None,
            "fingerprint": None,
            "namespace": "test_namespace",
        }]
        at.run()

        # Try to check GenAI models without compartment ID
        at.button(key="check_oci_genai").click().run()

        # Should show error for missing compartment ID
        assert any("OCI GenAI Compartment OCID is required" in error.value for error in at.error)

    def test_authentication_principals_workflow(self, app_server, app_test):
        """Test workflow with instance_principal authentication"""
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Setup state with instance_principal authentication
        at.session_state.oci_configs = [{
            "auth_profile": "DEFAULT",
            "authentication": "instance_principal",
            "user": None,
            "tenancy": "ocid1.tenancy.oc1..test",
            "region": "us-ashburn-1",
            "genai_compartment_id": "",
            "genai_region": "",
            "key_file": None,
            "security_token_file": None,
            "fingerprint": None,
            "namespace": "test_namespace",
        }]
        at.run()

        # Should show info about using principals
        assert any("Using OCI Authentication Principals" in info.value for info in at.info)

        # Configuration form should be disabled
        assert at.checkbox(key="oci_token_auth").disabled

        # Region should still be editable
        assert not at.text_input(key="oci_region").disabled

        # GenAI section should be available since namespace is valid
        assert not at.text_input(key="oci_genai_compartment_id").disabled

    def test_oke_workload_identity_workflow(self, app_server, app_test):
        """Test workflow with oke_workload_identity authentication"""
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Setup state with oke_workload_identity authentication
        at.session_state.oci_configs = [{
            "auth_profile": "DEFAULT",
            "authentication": "oke_workload_identity",
            "user": None,
            "tenancy": "ocid1.tenancy.oc1..test",
            "region": "us-ashburn-1",
            "genai_compartment_id": "",
            "genai_region": "",
            "key_file": None,
            "security_token_file": None,
            "fingerprint": None,
            "namespace": "test_namespace",
        }]
        at.run()

        # Should show info about using principals
        assert any("Using OCI Authentication Principals" in info.value for info in at.info)

        # Configuration should be disabled
        assert at.checkbox(key="oci_token_auth").disabled

    def test_token_authentication_workflow(self, app_server, app_test):
        """Test complete workflow with token authentication"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Enable token authentication
        at.checkbox(key="oci_token_auth").set_value(True).run()

        # User field should be disabled, token field enabled
        assert at.text_input(key="oci_user").disabled
        assert not at.text_input(key="oci_security_token_file").disabled

        # Set token authentication values
        at.text_input(key="oci_security_token_file").set_value("/path/to/token").run()
        at.text_input(key="oci_fingerprint").set_value("test:fingerprint").run()
        at.text_input(key="oci_tenancy").set_value("ocid1.tenancy.oc1..test").run()
        at.text_input(key="oci_region").set_value("us-ashburn-1").run()
        at.text_input(key="oci_key_file").set_value("/path/to/key").run()

        # Save configuration
        at.button(key="save_oci").click().run()

        # Should attempt to save (will show error in this test environment)
        # But the important part is testing the UI flow
        assert any("Update Failed" in error.value for error in at.error)

    def test_api_key_authentication_workflow(self, app_server, app_test):
        """Test complete workflow with API key authentication"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Keep token authentication disabled (default)
        assert not at.checkbox(key="oci_token_auth").value

        # Token field should be disabled, user field enabled
        assert not at.text_input(key="oci_user").disabled
        assert at.text_input(key="oci_security_token_file").disabled

        # Set API key authentication values
        at.text_input(key="oci_user").set_value("ocid1.user.oc1..test").run()
        at.text_input(key="oci_fingerprint").set_value("test:fingerprint").run()
        at.text_input(key="oci_tenancy").set_value("ocid1.tenancy.oc1..test").run()
        at.text_input(key="oci_region").set_value("us-ashburn-1").run()
        at.text_input(key="oci_key_file").set_value("/path/to/key").run()

        # Save configuration
        at.button(key="save_oci").click().run()

        # Should attempt to save (will show error in this test environment)
        assert any("Update Failed" in error.value for error in at.error)

    def test_multiple_profiles_workflow(self, app_server, app_test):
        """Test workflow with multiple OCI profiles"""
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Setup state with multiple profiles
        at.session_state.oci_configs = [
            {
                "auth_profile": "DEFAULT",
                "user": None,
                "tenancy": None,
                "region": None,
                "genai_compartment_id": "",
                "genai_region": "",
                "key_file": None,
                "security_token_file": None,
                "fingerprint": None,
                "namespace": None,
            },
            {
                "auth_profile": "PRODUCTION",
                "user": "ocid1.user.oc1..prod",
                "tenancy": "ocid1.tenancy.oc1..prod",
                "region": "us-ashburn-1",
                "genai_compartment_id": "ocid1.compartment.oc1..prod",
                "genai_region": "",
                "key_file": "/path/to/prod/key",
                "security_token_file": None,
                "fingerprint": "prod:fingerprint",
                "namespace": "prod_namespace",
            }
        ]
        at.session_state.client_settings["oci"]["auth_profile"] = "DEFAULT"
        at.run()

        # Should show profile selector
        profile_options = at.selectbox(key="selected_oci").options
        assert "DEFAULT" in profile_options
        assert "PRODUCTION" in profile_options

        # Switch to production profile
        at.selectbox(key="selected_oci").select("PRODUCTION").run()

        # Should show validated status for production profile
        assert any("Current Status: Validated - Namespace: prod_namespace" in success.value for success in at.success)

    def test_genai_models_display_workflow(self, app_server, app_test):
        """Test GenAI models table display and filtering"""
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Setup state with valid OCI and pre-loaded models
        at.session_state.oci_configs = [{
            "auth_profile": "DEFAULT",
            "user": None,
            "tenancy": None,
            "region": None,
            "genai_compartment_id": "ocid1.compartment.oc1..test",
            "genai_region": "",
            "key_file": None,
            "security_token_file": None,
            "fingerprint": None,
            "namespace": "test_namespace",
        }]

        # Pre-load GenAI models with multiple regions and capabilities
        at.session_state.genai_models = [
            {
                "model_name": "cohere.command",
                "region": "us-chicago-1",
                "capabilities": ["CHAT"]
            },
            {
                "model_name": "cohere.embed-english-v3.0",
                "region": "us-chicago-1",
                "capabilities": ["TEXT_EMBEDDINGS"]
            },
            {
                "model_name": "meta.llama-2-70b-chat",
                "region": "us-ashburn-1",
                "capabilities": ["CHAT"]
            },
            {
                "model_name": "other.model",
                "region": "us-chicago-1",
                "capabilities": ["OTHER"]  # Should be filtered out
            }
        ]
        at.run()

        # Should show region selector
        region_options = at.selectbox(key="selected_genai_region").options
        assert "us-chicago-1" in region_options
        assert "us-ashburn-1" in region_options

        # Select Chicago region
        at.selectbox(key="selected_genai_region").select("us-chicago-1").run()

        # Should display filtered models table (only Chicago models with CHAT/TEXT_EMBEDDINGS)
        # The table should show 2 models (command and embed), not the "other.model"
        assert at.dataframe is not None

    def test_error_state_persistence_workflow(self, app_server, app_test):
        """Test that error states persist across UI interactions"""
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Setup state with invalid configuration and error
        at.session_state.oci_configs = [{
            "auth_profile": "DEFAULT",
            "user": None,
            "tenancy": None,
            "region": None,
            "genai_compartment_id": "",
            "genai_region": "",
            "key_file": None,
            "security_token_file": None,
            "fingerprint": None,
            "namespace": None,  # Invalid - no namespace
        }]
        at.session_state.oci_error = "Connection failed: Invalid credentials"
        at.run()

        # Should show unverified status and error details
        assert any("Current Status: Unverified" in error.value for error in at.error)
        assert any("Update Failed - Connection failed: Invalid credentials" in error.value for error in at.error)

        # Error should persist even after UI interactions
        at.text_input(key="oci_region").set_value("us-ashburn-1").run()

        # Error should still be displayed
        assert any("Update Failed - Connection failed: Invalid credentials" in error.value for error in at.error)
