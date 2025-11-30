# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from test.integration.client.conftest import run_page_with_models_enabled


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    ST_FILE = "../src/client/content/testbed.py"

    def test_disabled(self, app_server, app_test):
        """Test everything is disabled as nothing configured"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        # When nothing is configured, one of these messages appears (depending on check order)
        valid_messages = [
            "No OpenAI compatible language models are configured and/or enabled. Disabling Testing Framework.",
            "Database is not configured. Disabling Testbed.",
        ]
        assert at.error[0].value in valid_messages and at.error[0].icon == "🛑"

    def test_page_loads(self, app_server, app_test):
        """Confirm page loads with model enabled"""
        run_page_with_models_enabled(app_server, app_test, self.ST_FILE)
