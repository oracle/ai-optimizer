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
