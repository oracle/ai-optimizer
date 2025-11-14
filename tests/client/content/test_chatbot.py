"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

from unittest.mock import patch


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    ST_FILE = "../src/client/content/chatbot.py"

    def test_disabled(self, app_server, app_test):
        """Test everything is disabled as nothing configured"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        assert (
            at.error[0].value == "No language models are configured and/or enabled. Disabling Client."
            and at.error[0].icon == "🛑"
        )


