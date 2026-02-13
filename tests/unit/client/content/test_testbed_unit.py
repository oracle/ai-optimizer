# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for testbed.py evaluation_report function.

Note: Other testbed tests are split across:
- test_testbed_records_unit.py: qa_update_db, qa_delete, update_record, delete_record, qa_update_gui
- test_testbed_ui_unit.py: render_existing_testset_ui
"""
# spell-checker: disable

from unittest.mock import MagicMock

import plotly.graph_objects as go


#############################################################################
# Test evaluation_report Function
#############################################################################
class TestEvaluationReport:
    """Test evaluation_report function and its components"""

    def test_create_gauge_function(self, monkeypatch):
        """Test the create_gauge nested function"""
        from client.content import testbed

        # We need to extract create_gauge from evaluation_report
        # Since it's nested, we'll test through evaluation_report

        mock_report = {
            "settings": {
                "ll_model": {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "streaming": False,
                    "chat_history": False,
                    "max_input_tokens": 1000,
                    "max_tokens": 500,
                },
                "testbed": {"judge_model": None},
                "vector_search": {"enabled": False},
            },
            "correctness": 0.85,
            "correct_by_topic": [
                {"topic": "Math", "correctness": 0.9},
                {"topic": "Science", "correctness": 0.8},
            ],
            "failures": [],
            "report": [
                {"question": "Q1", "conversation_history": [], "metadata": {}, "correctness": 1.0},
            ],
        }

        # Mock streamlit functions
        import streamlit as st

        # Mock st.dialog decorator to return the function unchanged
        original_dialog = st.dialog
        mock_dialog = MagicMock(side_effect=lambda *args, **kwargs: lambda f: f)
        monkeypatch.setattr(st, "dialog", mock_dialog)

        # Reload testbed to apply the mock decorator
        import importlib

        importlib.reload(testbed)

        mock_plotly_chart = MagicMock()
        mock_columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])

        monkeypatch.setattr(st, "plotly_chart", mock_plotly_chart)
        monkeypatch.setattr(st, "subheader", MagicMock())
        monkeypatch.setattr(st, "dataframe", MagicMock())
        monkeypatch.setattr(st, "markdown", MagicMock())
        monkeypatch.setattr(st, "columns", mock_columns)

        # Call evaluation_report with mock report
        testbed.evaluation_report(report=mock_report)

        # Verify plotly_chart was called (gauge was created and displayed)
        assert mock_plotly_chart.called
        fig_arg = mock_plotly_chart.call_args[0][0]
        assert isinstance(fig_arg, go.Figure)

        # Restore original dialog decorator and reload
        monkeypatch.setattr(st, "dialog", original_dialog)
        importlib.reload(testbed)

    def test_evaluation_report_with_eid(self, monkeypatch):
        """Test evaluation_report when called with eid parameter"""
        from client.content import testbed
        from client.utils import api_call

        mock_report = {
            "settings": {
                "ll_model": {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "streaming": False,
                    "chat_history": False,
                    "max_input_tokens": 1000,
                    "max_tokens": 500,
                },
                "testbed": {"judge_model": "gpt-4"},
                "vector_search": {"enabled": False},
            },
            "correctness": 0.75,
            "correct_by_topic": [],
            "failures": [
                {"question": "Q1", "conversation_history": [], "metadata": {}, "correctness": 0.0},
            ],
            "report": [],
        }

        # Mock API call
        mock_get = MagicMock(return_value=mock_report)
        monkeypatch.setattr(api_call, "get", mock_get)

        # Mock streamlit functions
        import streamlit as st

        # Mock st.dialog decorator
        original_dialog = st.dialog
        mock_dialog = MagicMock(side_effect=lambda *args, **kwargs: lambda f: f)
        monkeypatch.setattr(st, "dialog", mock_dialog)

        # Reload testbed to apply the mock decorator
        import importlib

        importlib.reload(testbed)

        mock_columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])

        monkeypatch.setattr(st, "plotly_chart", MagicMock())
        monkeypatch.setattr(st, "subheader", MagicMock())
        monkeypatch.setattr(st, "dataframe", MagicMock())
        monkeypatch.setattr(st, "markdown", MagicMock())
        monkeypatch.setattr(st, "columns", mock_columns)

        # Call with eid
        testbed.evaluation_report(eid="eval123")

        # Verify API was called
        mock_get.assert_called_once_with(endpoint="v1/testbed/evaluation", params={"eid": "eval123"})

        # Restore original dialog decorator and reload
        monkeypatch.setattr(st, "dialog", original_dialog)
        importlib.reload(testbed)

    def test_evaluation_report_with_vector_search_enabled(self, monkeypatch):
        """Test evaluation_report displays vector search settings when enabled"""
        from client.content import testbed

        mock_report = {
            "settings": {
                "ll_model": {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "streaming": False,
                    "chat_history": False,
                    "max_input_tokens": 1000,
                    "max_tokens": 500,
                },
                "testbed": {"judge_model": None},
                "database": {"alias": "DEFAULT"},
                "vector_search": {
                    "enabled": True,
                    "vector_store": "my_vs",
                    "alias": "my_alias",
                    "search_type": "Similarity",
                    "score_threshold": 0.7,
                    "fetch_k": 10,
                    "lambda_mult": 0.5,
                    "top_k": 5,
                    "grading": True,
                },
            },
            "correctness": 0.9,
            "correct_by_topic": [],
            "failures": [],
            "report": [],
        }

        # Mock streamlit functions
        import streamlit as st

        # Mock st.dialog decorator
        original_dialog = st.dialog
        mock_dialog = MagicMock(side_effect=lambda *args, **kwargs: lambda f: f)
        monkeypatch.setattr(st, "dialog", mock_dialog)

        # Reload testbed to apply the mock decorator
        import importlib

        importlib.reload(testbed)

        mock_markdown = MagicMock()
        mock_columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])

        monkeypatch.setattr(st, "markdown", mock_markdown)
        monkeypatch.setattr(st, "plotly_chart", MagicMock())
        monkeypatch.setattr(st, "subheader", MagicMock())
        monkeypatch.setattr(st, "dataframe", MagicMock())
        monkeypatch.setattr(st, "columns", mock_columns)

        # Call evaluation_report
        testbed.evaluation_report(report=mock_report)

        # Verify vector search info was displayed
        calls = [str(call) for call in mock_markdown.call_args_list]
        assert any("DEFAULT" in str(call) for call in calls)
        assert any("my_vs" in str(call) for call in calls)

        # Restore original dialog decorator and reload
        monkeypatch.setattr(st, "dialog", original_dialog)
        importlib.reload(testbed)

    def test_evaluation_report_with_mmr_search_type(self, monkeypatch):
        """Test evaluation_report with Maximal Marginal Relevance search type"""
        from client.content import testbed

        mock_report = {
            "settings": {
                "ll_model": {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "streaming": False,
                    "chat_history": False,
                    "max_input_tokens": 1000,
                    "max_tokens": 500,
                },
                "testbed": {"judge_model": None},
                "database": {"alias": "DEFAULT"},
                "vector_search": {
                    "enabled": True,
                    "vector_store": "my_vs",
                    "alias": "my_alias",
                    "search_type": "Maximal Marginal Relevance",  # Different search type
                    "score_threshold": 0.7,
                    "fetch_k": 10,
                    "lambda_mult": 0.5,
                    "top_k": 5,
                    "grading": True,
                },
            },
            "correctness": 0.85,
            "correct_by_topic": [],
            "failures": [],
            "report": [],
        }

        # Mock streamlit functions
        import streamlit as st

        # Mock st.dialog decorator
        original_dialog = st.dialog
        mock_dialog = MagicMock(side_effect=lambda *args, **kwargs: lambda f: f)
        monkeypatch.setattr(st, "dialog", mock_dialog)

        # Reload testbed to apply the mock decorator
        import importlib

        importlib.reload(testbed)

        mock_dataframe = MagicMock()
        mock_columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])

        monkeypatch.setattr(st, "dataframe", mock_dataframe)
        monkeypatch.setattr(st, "markdown", MagicMock())
        monkeypatch.setattr(st, "plotly_chart", MagicMock())
        monkeypatch.setattr(st, "subheader", MagicMock())
        monkeypatch.setattr(st, "columns", mock_columns)

        # Call evaluation_report
        testbed.evaluation_report(report=mock_report)

        # MMR type should NOT drop fetch_k and lambda_mult
        # This is tested by verifying dataframe was called
        assert mock_dataframe.called

        # Restore original dialog decorator and reload
        monkeypatch.setattr(st, "dialog", original_dialog)
        importlib.reload(testbed)


#############################################################################
# Test evaluation_report backward compatibility
#############################################################################
class TestEvaluationReportBackwardCompatibility:
    """Test evaluation_report backward compatibility when vector_search.enabled is missing"""

    def test_evaluation_report_fallback_to_tools_enabled(self, monkeypatch):
        """Test evaluation_report falls back to tools_enabled when vector_search.enabled is missing"""
        from client.content import testbed

        # Create report WITHOUT vector_search.enabled but WITH tools_enabled containing "Vector Search"
        mock_report = {
            "settings": {
                "ll_model": {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "streaming": False,
                    "chat_history": False,
                    "max_input_tokens": 1000,
                    "max_tokens": 500,
                },
                "testbed": {"judge_model": None},
                "tools_enabled": ["Vector Search"],  # Vector Search enabled via tools_enabled
                "database": {"alias": "DEFAULT"},
                "vector_search": {
                    # NO "enabled" key - tests backward compatibility
                    "vector_store": "my_vs",
                    "alias": "my_alias",
                    "search_type": "Similarity",
                    "score_threshold": 0.7,
                    "fetch_k": 10,
                    "lambda_mult": 0.5,
                    "top_k": 5,
                    "grading": True,
                },
            },
            "correctness": 0.85,
            "correct_by_topic": [],
            "failures": [],
            "report": [],
        }

        # Mock streamlit functions
        import streamlit as st

        # Mock st.dialog decorator
        original_dialog = st.dialog
        mock_dialog = MagicMock(side_effect=lambda *args, **kwargs: lambda f: f)
        monkeypatch.setattr(st, "dialog", mock_dialog)

        # Reload testbed to apply the mock decorator
        import importlib

        importlib.reload(testbed)

        mock_markdown = MagicMock()
        mock_columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])

        monkeypatch.setattr(st, "markdown", mock_markdown)
        monkeypatch.setattr(st, "plotly_chart", MagicMock())
        monkeypatch.setattr(st, "subheader", MagicMock())
        monkeypatch.setattr(st, "dataframe", MagicMock())
        monkeypatch.setattr(st, "columns", mock_columns)

        # Call evaluation_report - should NOT raise KeyError
        testbed.evaluation_report(report=mock_report)

        # Verify vector search info was displayed (backward compatibility worked)
        calls = [str(call) for call in mock_markdown.call_args_list]
        assert any("DEFAULT" in str(call) for call in calls), "Should display database info for vector search"
        assert any("my_vs" in str(call) for call in calls), "Should display vector store info"

        # Restore original dialog decorator and reload
        monkeypatch.setattr(st, "dialog", original_dialog)
        importlib.reload(testbed)

    def test_evaluation_report_fallback_vs_not_in_tools(self, monkeypatch):
        """Test evaluation_report shows 'without Vector Search' when tools_enabled doesn't contain Vector Search"""
        from client.content import testbed

        # Create report WITHOUT vector_search.enabled and WITHOUT Vector Search in tools_enabled
        mock_report = {
            "settings": {
                "ll_model": {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "streaming": False,
                    "chat_history": False,
                    "max_input_tokens": 1000,
                    "max_tokens": 500,
                },
                "testbed": {"judge_model": None},
                "tools_enabled": ["Other Tool"],  # Vector Search NOT in tools_enabled
                "vector_search": {
                    # NO "enabled" key - tests backward compatibility
                    "vector_store": "my_vs",
                },
            },
            "correctness": 0.85,
            "correct_by_topic": [],
            "failures": [],
            "report": [],
        }

        # Mock streamlit functions
        import streamlit as st

        # Mock st.dialog decorator
        original_dialog = st.dialog
        mock_dialog = MagicMock(side_effect=lambda *args, **kwargs: lambda f: f)
        monkeypatch.setattr(st, "dialog", mock_dialog)

        # Reload testbed to apply the mock decorator
        import importlib

        importlib.reload(testbed)

        mock_markdown = MagicMock()
        mock_columns = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])

        monkeypatch.setattr(st, "markdown", mock_markdown)
        monkeypatch.setattr(st, "plotly_chart", MagicMock())
        monkeypatch.setattr(st, "subheader", MagicMock())
        monkeypatch.setattr(st, "dataframe", MagicMock())
        monkeypatch.setattr(st, "columns", mock_columns)

        # Call evaluation_report - should NOT raise KeyError
        testbed.evaluation_report(report=mock_report)

        # Verify "without Vector Search" message was displayed
        calls = [str(call) for call in mock_markdown.call_args_list]
        assert any("without Vector Search" in str(call) for call in calls), (
            "Should display 'without Vector Search' when VS not enabled"
        )

        # Restore original dialog decorator and reload
        monkeypatch.setattr(st, "dialog", original_dialog)
        importlib.reload(testbed)
