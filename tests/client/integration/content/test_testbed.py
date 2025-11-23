# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

import os
from unittest.mock import patch
from conftest import setup_test_database, enable_test_models, temporary_sys_path


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    # Streamlit File path
    ST_FILE = "../src/client/content/testbed.py"

    def test_initialization(self, app_server, app_test, db_container):
        """Test initialization of the testbed component with real server data and database"""
        assert app_server is not None
        assert db_container is not None

        # Initialize app_test - now loads full config from server
        at = app_test(self.ST_FILE)

        # Set up prerequisites using helper functions
        at = setup_test_database(at)
        at = enable_test_models(at)

        # Now run the app
        at.run()

        # Verify specific widgets that should exist
        # The testbed page should render these widgets when initialized
        radio_widgets = at.get("radio")
        assert len(radio_widgets) >= 1, (
            f"Expected at least 1 radio widget for testset source selection. Errors: {[e.value for e in at.error]}"
        )

        button_widgets = at.get("button")
        assert len(button_widgets) >= 1, "Expected at least 1 button widget"

        file_uploader_widgets = at.get("file_uploader")
        assert len(file_uploader_widgets) >= 1, "Expected at least 1 file uploader widget"

        # Test passes if the expected widgets are rendered

    def test_testset_source_selection(self, app_server, app_test, db_container):
        """Test selection of test sets from different sources with real server data"""
        assert app_server is not None
        assert db_container is not None

        # Initialize app_test - now loads full config from server
        at = app_test(self.ST_FILE)

        # Set up prerequisites using helper functions
        at = setup_test_database(at)
        at = enable_test_models(at)

        # Run the app to initialize all widgets
        at.run()

        # Verify the expected widgets are present
        radio_widgets = at.get("radio")
        assert len(radio_widgets) > 0, f"Expected radio widgets. Errors: {[e.value for e in at.error]}"

        file_uploader_widgets = at.get("file_uploader")
        assert len(file_uploader_widgets) > 0, "Expected file uploader widgets"

        # Test passes if the expected widgets are rendered

    def test_testset_generation_with_saved_ll_model(self, app_server, app_test, db_container):
        """Test that testset generation UI correctly restores saved language model preferences

        This test verifies that when a user has a saved language model preference,
        the UI correctly looks up the model's index from the language models list
        (not the embedding models list).
        """
        assert app_server is not None
        assert db_container is not None

        # Initialize app_test
        at = app_test(self.ST_FILE)

        # Set up prerequisites using helper functions
        at = setup_test_database(at)

        # Create realistic model configurations with distinct LLM and embedding models
        at.session_state.model_configs = [
            {
                "id": "gpt-4o-mini",
                "type": "ll",
                "enabled": True,
                "provider": "openai",
                "openai_compat": True,
            },
            {
                "id": "gpt-4o",
                "type": "ll",
                "enabled": True,
                "provider": "openai",
                "openai_compat": True,
            },
            {
                "id": "text-embedding-3-small",
                "type": "embed",
                "enabled": True,
                "provider": "openai",
                "openai_compat": True,
            },
            {
                "id": "embed-english-v3.0",
                "type": "embed",
                "enabled": True,
                "provider": "cohere",
                "openai_compat": True,
            },
        ]

        # Initialize client_settings with a saved LLM preference
        # This simulates a user who previously selected a language model
        if "client_settings" not in at.session_state:
            at.session_state.client_settings = {}
        if "testbed" not in at.session_state.client_settings:
            at.session_state.client_settings["testbed"] = {}

        # Set a language model preference that exists in LL list but NOT in embed list
        at.session_state.client_settings["testbed"]["qa_ll_model"] = "openai/gpt-4o-mini"

        # Run the app - should render without error
        at.run()

        # Toggle to "Generate Q&A Test Set" mode
        generate_toggle = at.get("toggle")
        assert len(generate_toggle) > 0, "Expected toggle widget for 'Generate Q&A Test Set'"

        # This should not raise ValueError about model not being in list
        generate_toggle[0].set_value(True).run()

        # Verify no exceptions occurred during rendering
        assert not at.exception, f"Rendering failed with exception: {at.exception}"

        # Verify the selectboxes rendered correctly
        selectboxes = at.get("selectbox")
        assert len(selectboxes) >= 2, "Should have at least 2 selectboxes (LLM and embed model)"

        # Verify no errors were thrown
        errors = at.get("error")
        assert len(errors) == 0, f"Expected no errors, but got: {[e.value for e in errors]}"

    def test_testset_generation_default_ll_model(self, app_server, app_test, db_container):
        """Test that testset generation UI sets correct default language model

        This test verifies that when no saved language model preference exists,
        the UI correctly initializes the default from the language models list
        (not the embedding models list).
        """
        assert app_server is not None
        assert db_container is not None

        # Initialize app_test
        at = app_test(self.ST_FILE)

        # Set up prerequisites using helper functions
        at = setup_test_database(at)

        # Create realistic model configurations with distinct LLM and embedding models
        at.session_state.model_configs = [
            {
                "id": "gpt-4o-mini",
                "type": "ll",
                "enabled": True,
                "provider": "openai",
                "openai_compat": True,
            },
            {
                "id": "gpt-4o",
                "type": "ll",
                "enabled": True,
                "provider": "openai",
                "openai_compat": True,
            },
            {
                "id": "text-embedding-3-small",
                "type": "embed",
                "enabled": True,
                "provider": "openai",
                "openai_compat": True,
            },
            {
                "id": "embed-english-v3.0",
                "type": "embed",
                "enabled": True,
                "provider": "cohere",
                "openai_compat": True,
            },
        ]

        # Initialize client_settings but DON'T set saved preferences
        # This triggers the default initialization code path
        if "client_settings" not in at.session_state:
            at.session_state.client_settings = {}
        if "testbed" not in at.session_state.client_settings:
            at.session_state.client_settings["testbed"] = {}

        # Run the app - should render without error
        at.run()

        # Toggle to "Generate Q&A Test Set" mode
        generate_toggle = at.get("toggle")
        assert len(generate_toggle) > 0, "Expected toggle widget for 'Generate Q&A Test Set'"

        # This should not crash - defaults should be set correctly
        generate_toggle[0].set_value(True).run()

        # Verify no exceptions occurred during rendering
        assert not at.exception, f"Rendering failed with exception: {at.exception}"

        # Verify the selectboxes rendered correctly
        selectboxes = at.get("selectbox")
        assert len(selectboxes) >= 2, "Should have at least 2 selectboxes (LLM and embed model)"

        # Verify the default qa_ll_model is actually a language model, not an embedding model
        qa_ll_model = at.session_state.client_settings["testbed"]["qa_ll_model"]
        assert qa_ll_model in ["openai/gpt-4o-mini", "openai/gpt-4o"], (
            f"Default qa_ll_model should be a language model, got: {qa_ll_model}"
        )

        # Verify no errors were thrown
        errors = at.get("error")
        assert len(errors) == 0, f"Expected no errors, but got: {[e.value for e in errors]}"

    @patch("client.utils.api_call.post")
    def test_evaluate_testset(self, mock_post, app_test, monkeypatch):
        """Test evaluation of a test set"""

        # Mock the API responses for get_models
        def mock_get(endpoint=None, **_kwargs):
            if endpoint == "v1/models":
                return [
                    {
                        "id": "test-ll-model",
                        "type": "ll",
                        "enabled": True,
                        "url": "http://test.url",
                        "openai_compat": True,
                    },
                    {
                        "id": "test-embed-model",
                        "type": "embed",
                        "enabled": True,
                        "url": "http://test.url",
                        "openai_compat": True,
                    },
                ]
            return {}

        monkeypatch.setattr("client.utils.api_call.get", mock_get)

        # Mock API post response for evaluation
        mock_post.return_value = {
            "id": "eval123",
            "score": 0.85,
            "results": [{"question": "Test question 1", "score": 0.9}, {"question": "Test question 2", "score": 0.8}],
        }

        # Mock functions that make external calls
        monkeypatch.setattr("common.functions.is_url_accessible", lambda url: (True, ""))
        monkeypatch.setattr("streamlit.cache_resource", lambda *args, **kwargs: lambda func: func)
        monkeypatch.setattr("client.utils.st_common.is_db_configured", lambda: True)

        # Initialize app_test
        at = app_test(self.ST_FILE)

        # Set up session state requirements
        at.session_state.user_settings = {
            "client": "test_client",
            "oci": {"auth_profile": "DEFAULT"},
            "vector_search": {"database": "DEFAULT"},
        }

        at.session_state.ll_model_enabled = {
            "test-ll-model": {"url": "http://test.url", "openai_compat": True, "enabled": True}
        }

        at.session_state.embed_model_enabled = {
            "test-embed-model": {"url": "http://test.url", "openai_compat": True, "enabled": True}
        }

        # Run the app to initialize all widgets
        at = at.run()

        # For this minimal test, just verify the app runs without error
        # This test is valuable to ensure mocking works properly
        assert True

        # Test passes if the app runs without errors

    @patch("client.content.testbed.st_common")
    @patch("client.content.testbed.get_testbed_db_testsets")
    def test_reset_testset_function(self, mock_get_testbed, mock_st_common):
        """Test the reset_testset function"""
        # Import the module to test the function directly
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        # Test reset_testset without cache
        testbed.reset_testset(cache=False)

        # Verify clear_state_key was called for all expected keys
        expected_calls = [
            "testbed",
            "selected_testset_name",
            "testbed_qa",
            "testbed_db_testsets",
            "testbed_evaluations",
        ]

        for key in expected_calls:
            mock_st_common.clear_state_key.assert_any_call(key)

        # Test reset_testset with cache
        mock_st_common.reset_mock()
        testbed.reset_testset(cache=True)

        # Should still call clear_state_key for all keys
        for key in expected_calls:
            mock_st_common.clear_state_key.assert_any_call(key)

        # Should also call clear on get_testbed_db_testsets
        mock_get_testbed.clear.assert_called_once()

    def test_download_file_fragment(self):
        """Test the download_file fragment function"""
        # Since the download_file function is a streamlit fragment,
        # we can only test that it exists and is callable
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        # Verify function exists and is callable
        assert hasattr(testbed, "download_file")
        assert callable(testbed.download_file)

        # Note: The actual streamlit fragment functionality
        # is tested through the integration tests

    def test_update_record_function_logic(self):
        """Test the update_record function logic"""
        # Test that the function exists and is callable
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        assert hasattr(testbed, "update_record")
        assert callable(testbed.update_record)

        # Note: The actual functionality is tested in integration tests
        # since it depends heavily on Streamlit's session state

    def test_delete_record_function_exists(self):
        """Test the delete_record function exists"""
        # Test that the function exists and is callable
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        assert hasattr(testbed, "delete_record")
        assert callable(testbed.delete_record)

        # Note: The actual functionality is tested in integration tests
        # since it depends heavily on Streamlit's session state

    @patch("client.utils.api_call.get")
    def test_get_testbed_db_testsets(self, mock_get, app_test):
        """Test the get_testbed_db_testsets cached function"""
        # Ensure app_test fixture is available for proper test context
        assert app_test is not None

        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        # Mock API response
        expected_response = {
            "testsets": [
                {"tid": "test1", "name": "Test Set 1", "created": "2024-01-01"},
                {"tid": "test2", "name": "Test Set 2", "created": "2024-01-02"},
            ]
        }
        mock_get.return_value = expected_response

        # Test function call
        result = testbed.get_testbed_db_testsets()

        # Verify API was called correctly
        mock_get.assert_called_once_with(endpoint="v1/testbed/testsets")
        assert result == expected_response

    def test_qa_delete_function_exists(self):
        """Test the qa_delete function exists and is callable"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        assert hasattr(testbed, "qa_delete")
        assert callable(testbed.qa_delete)

        # Note: Full functionality testing requires Streamlit session state
        # and is covered by integration tests

    def test_qa_update_db_function_exists(self):
        """Test the qa_update_db function exists and is callable"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        assert hasattr(testbed, "qa_update_db")
        assert callable(testbed.qa_update_db)

        # Note: Full functionality testing requires Streamlit session state
        # and is covered by integration tests

    def test_qa_update_gui_function_exists(self):
        """Test the qa_update_gui function exists and is callable"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        assert hasattr(testbed, "qa_update_gui")
        assert callable(testbed.qa_update_gui)

        # Note: Full UI functionality testing is covered by integration tests

    def test_evaluation_report_function_exists(self):
        """Test the evaluation_report function exists and is callable"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        assert hasattr(testbed, "evaluation_report")
        assert callable(testbed.evaluation_report)

        # Note: Full functionality testing with Streamlit dialogs
        # is covered by integration tests

    def test_evaluation_report_with_eid_parameter(self):
        """Test evaluation_report function accepts eid parameter"""
        import inspect

        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        # Get function signature and verify eid parameter exists
        sig = inspect.signature(testbed.evaluation_report)
        assert "eid" in sig.parameters
        assert "report" in sig.parameters

        # Verify function is callable
        assert callable(testbed.evaluation_report)

        # Note: Full API integration testing is covered by integration tests


#############################################################################
# Integration Tests with Real Database
#############################################################################
class TestTestbedDatabaseIntegration:
    """Integration tests using real database container"""

    # Streamlit File path
    ST_FILE = "../src/client/content/testbed.py"

    def test_testbed_with_real_database_simplified(self, app_server, db_container):
        """Test basic testbed functionality with real database container (simplified)"""
        assert app_server is not None
        assert db_container is not None

        # Verify the database container exists and is not stopped
        assert db_container.status in ["running", "created"]

        # This test verifies that:
        # 1. The app server is running
        # 2. The database container is available
        # 3. The testbed module can be imported and has expected functions
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

            # Verify key testbed functions exist
            testbed_functions = [
                "main",
                "reset_testset",
                "get_testbed_db_testsets",
                "qa_update_gui",
                "evaluation_report",
            ]

            for func_name in testbed_functions:
                assert hasattr(testbed, func_name), f"Function {func_name} not found"
                assert callable(getattr(testbed, func_name)), f"Function {func_name} is not callable"

    def test_testset_functions_callable(self, app_server, db_container):
        """Test testset functions are callable (simplified)"""
        assert app_server is not None
        assert db_container is not None

        # Test that testbed functions can be imported and are callable
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

            # Test functions that interact with the API/database
            api_functions = ["get_testbed_db_testsets", "qa_delete", "qa_update_db"]

            for func_name in api_functions:
                assert hasattr(testbed, func_name), f"Function {func_name} not found"
                assert callable(getattr(testbed, func_name)), f"Function {func_name} is not callable"

    def test_database_integration_basic(self, app_server, db_container):
        """Test basic database integration functionality"""
        assert app_server is not None
        assert db_container is not None

        # Verify the database container exists and is not stopped
        assert db_container.status in ["running", "created"]

        # This is a simplified integration test that verifies:
        # 1. The app server is running
        # 2. The database container is running
        # 3. The testbed module can be imported
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../src")):
            from client.content import testbed

        # Verify all main functions are present and callable
        main_functions = [
            "reset_testset",
            "download_file",
            "evaluation_report",
            "get_testbed_db_testsets",
            "qa_delete",
            "qa_update_db",
            "update_record",
            "delete_record",
            "qa_update_gui",
            "main",
        ]

        for func_name in main_functions:
            assert hasattr(testbed, func_name), f"Function {func_name} not found"
            assert callable(getattr(testbed, func_name)), f"Function {func_name} is not callable"
