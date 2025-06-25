"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

import re
import pytest

from conftest import TEST_CONFIG


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    # Streamlit File
    ST_FILE = "../src/client/content/config/databases.py"

    def test_missing_details(self, app_server, app_test):
        """Submits with missing required inputs"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        assert at.session_state.database_config is not None
        at.button[0].click().run()
        assert at.error[0].value == "Current Status: Disconnected"
        assert (
            at.error[1].value == "Update Failed - Database: DEFAULT missing connection details."
            and at.error[1].icon == "🚨"
        )
        assert at.session_state.database_config["DEFAULT"]["user"] is None
        assert at.session_state.database_config["DEFAULT"]["password"] is None
        assert at.session_state.database_config["DEFAULT"]["dsn"] is None
        assert at.session_state.database_config["DEFAULT"]["wallet_password"] is None
        assert at.session_state.database_config["DEFAULT"]["wallet_location"] is None
        assert at.session_state.database_config["DEFAULT"]["config_dir"] is not None
        assert at.session_state.database_config["DEFAULT"]["tcp_connect_timeout"] is not None
        assert at.session_state.database_config["DEFAULT"]["connected"] is False
        assert at.session_state.database_config["DEFAULT"]["vector_stores"] is None

    def test_wrong_details(self, app_server, app_test):
        """Submits with wrong details"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        assert at.session_state.database_config is not None
        at.text_input(key="database_user").set_value(TEST_CONFIG["db_username"]).run()
        at.text_input(key="database_password").set_value(TEST_CONFIG["db_password"]).run()
        at.text_input(key="database_dsn").set_value(TEST_CONFIG["db_dsn"]).run()
        at.button[0].click().run()
        assert at.error[0].value == "Current Status: Disconnected"
        assert at.error[1].value == "Update Failed - Database: DEFAULT unable to connect." and at.error[1].icon == "🚨"
        assert at.session_state.database_config["DEFAULT"]["user"] is None
        assert at.session_state.database_config["DEFAULT"]["password"] is None
        assert at.session_state.database_config["DEFAULT"]["dsn"] is None
        assert at.session_state.database_config["DEFAULT"]["wallet_password"] is None
        assert at.session_state.database_config["DEFAULT"]["wallet_location"] is None
        assert at.session_state.database_config["DEFAULT"]["config_dir"] is not None
        assert at.session_state.database_config["DEFAULT"]["tcp_connect_timeout"] is not None
        assert at.session_state.database_config["DEFAULT"]["connected"] is False
        assert at.session_state.database_config["DEFAULT"]["vector_stores"] is None

    def test_connected(self, app_server, app_test, db_container):
        """Sumbits with good DSN"""
        assert app_server is not None
        assert db_container is not None
        at = app_test(self.ST_FILE).run()
        assert at.session_state.database_config is not None
        at.text_input(key="database_user").set_value(TEST_CONFIG["db_username"]).run()
        at.text_input(key="database_password").set_value(TEST_CONFIG["db_password"]).run()
        at.text_input(key="database_dsn").set_value(TEST_CONFIG["db_dsn"]).run()
        at.button[0].click().run()
        assert at.success[0].value == "Current Status: Connected"
        assert at.toast[0].value == "Update Successful." and at.toast[0].icon == "✅"
        at.button[0].click().run()
        assert at.info[0].value == "DEFAULT Database Configuration - No Changes Detected." and at.info[0].icon == "ℹ️"
        assert at.session_state.database_config["DEFAULT"]["user"] == TEST_CONFIG["db_username"]
        assert at.session_state.database_config["DEFAULT"]["password"] == TEST_CONFIG["db_password"]
        assert at.session_state.database_config["DEFAULT"]["dsn"] == TEST_CONFIG["db_dsn"]
        assert at.session_state.database_config["DEFAULT"]["wallet_password"] is None
        assert at.session_state.database_config["DEFAULT"]["wallet_location"] is None
        assert at.session_state.database_config["DEFAULT"]["config_dir"] is not None
        assert at.session_state.database_config["DEFAULT"]["tcp_connect_timeout"] is not None
        assert at.session_state.database_config["DEFAULT"]["connected"] is True
        assert at.session_state.database_config["DEFAULT"]["vector_stores"] == []

    test_cases = [
        pytest.param(
            {
                "alias": "DEFAULT",
                "username": "",
                "password": TEST_CONFIG["db_password"],
                "dsn": TEST_CONFIG["db_dsn"],
                "expected": "Update Failed - Database: DEFAULT missing connection details.",
            },
            id="missing_input",
        ),
        pytest.param(
            {
                "alias": "DEFAULT",
                "username": "ADMIN",
                "password": TEST_CONFIG["db_password"],
                "dsn": TEST_CONFIG["db_dsn"],
                "expected": "Update Failed - Database: DEFAULT invalid credentials.",
            },
            id="bad_user",
        ),
        pytest.param(
            {
                "alias": "DEFAULT",
                "username": TEST_CONFIG["db_username"],
                "password": "Wr0ng_P4ssW0rd",
                "dsn": TEST_CONFIG["db_dsn"],
                "expected": "Update Failed - Database: DEFAULT invalid credentials.",
            },
            id="bad_password",
        ),
        pytest.param(
            {
                "alias": "DEFAULT",
                "username": TEST_CONFIG["db_username"],
                "password": TEST_CONFIG["db_password"],
                "dsn": "//localhost:1521/WRONG_TP",
                "expected": "Update Failed - Database: DEFAULT unable to connect.",
            },
            id="bad_dsn_easy",
        ),
        pytest.param(
            {
                "alias": "DEFAULT",
                "username": TEST_CONFIG["db_username"],
                "password": TEST_CONFIG["db_password"],
                "dsn": "WRONG_TP",
                "expected": "Update Failed - Database: DEFAULT DPY-*",
            },
            id="bad_dsn",
        ),
    ]

    @pytest.mark.parametrize("test_case", test_cases)
    def test_disconnected(self, app_server, app_test, db_container, test_case):
        """Submits with incorrect details"""
        assert app_server is not None
        assert db_container is not None
        at = app_test(self.ST_FILE).run()
        assert at.session_state.database_config is not None
        at.text_input(key="database_user").set_value(test_case["username"]).run()
        at.text_input(key="database_password").set_value(test_case["password"]).run()
        at.text_input(key="database_dsn").set_value(test_case["dsn"]).run()
        at.button[0].click().run()
        assert at.error[0].value == "Current Status: Disconnected"
        assert re.match(test_case["expected"], at.error[1].value) and at.error[1].icon == "🚨"
        # Due to the connection error, the settings should NOT be updated and be set
        # to previous successful test connection; connected will be False for error handling
        assert at.session_state.database_config["DEFAULT"]["user"] == TEST_CONFIG["db_username"]
        assert at.session_state.database_config["DEFAULT"]["password"] == TEST_CONFIG["db_password"]
        assert at.session_state.database_config["DEFAULT"]["dsn"] == TEST_CONFIG["db_dsn"]
        assert at.session_state.database_config["DEFAULT"]["wallet_password"] is None
        assert at.session_state.database_config["DEFAULT"]["wallet_location"] is None
        assert at.session_state.database_config["DEFAULT"]["config_dir"] is not None
        assert at.session_state.database_config["DEFAULT"]["tcp_connect_timeout"] is not None
        assert at.session_state.database_config["DEFAULT"]["connected"] is False
        assert at.session_state.database_config["DEFAULT"]["vector_stores"] == []

    def test_vector_stores(self, app_server, app_test, db_container):
        """Test Vector Storage Form"""
        assert app_server is not None
        assert db_container is not None
        at = app_test(self.ST_FILE).run()
        assert at.session_state.database_config is not None
        # Populate Vector Storage State
        at.session_state.database_config["DEFAULT"]["vector_stores"] = [
            {
                "vector_store": "VS_USERS_TEXT_EMBEDDING_3_SMALL_8191_1639_COSINE_HNSW",
                "alias": "TEST1",
                "model": "text-embedding-3-small",
                "chunk_size": 8191,
                "chunk_overlap": 1639,
                "distance_metric": "COSINE",
                "index_type": "HNSW",
            },
            {
                "vector_store": "VS_USERS_TEXT_EMBEDDING_3_SMALL_510_102_COSINE_HNSW",
                "alias": "TEST2",
                "model": "text-embedding-3-small",
                "chunk_size": 510,
                "chunk_overlap": 102,
                "distance_metric": "COSINE",
                "index_type": "HNSW",
            },
        ]
        # Mimic Connected to show additional forms
        at.session_state.database_config["DEFAULT"]["connected"] = True
        # Refresh the Page
        at.run()
        for vs in at.session_state.database_config["DEFAULT"]["vector_stores"]:
            vector_store = vs["vector_store"].lower()
            assert at.button(key=f"vector_stores_{vector_store}").icon == "🗑️"
            fields = ["alias", "model", "chunk_size", "chunk_overlap", "distance_metric", "index_type"]
            for field in fields:
                assert at.text_input(key=f"vector_stores_{vector_store}_{field}").label == field.capitalize()
                assert at.text_input(key=f"vector_stores_{vector_store}_{field}").value == str(vs[field])

        # Drop a Vector Store
        at.button[1].click().run()
        assert "dropped" in at.toast[0].value and at.toast[0].icon == "✅"
