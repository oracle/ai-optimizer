"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.testbed (functions only — not module-level page code)
"""
# spell-checker: disable

import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from client.tests.conftest import AttrDict, make_http_error

MODULE = "client.app.content.testbed"
HELPERS = "client.app.core.helpers"
API = "client.app.core.api"
SIDEBAR = "client.app.core.sidebar"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_state(extra=None):
    """Build a minimal AttrDict mimicking session_state for testbed tests."""
    data = AttrDict(
        {
            "settings": {
                "database_configs": [{"alias": "testdb"}],
                "model_configs": [],
                "client_settings": {
                    "database": {"alias": "testdb"},
                },
            },
            "optimizer_client": "test-client",
        }
    )
    if extra:
        data.update(extra)
    return data


def _qa_records(count=3):
    """Build a list of Q&A record dicts."""
    return [
        {
            "question": f"Q{i}",
            "reference_answer": f"A{i}",
            "reference_context": f"C{i}",
            "metadata": f"M{i}",
        }
        for i in range(count)
    ]


SAMPLE_REPORT = {
    "settings": {
        "ll_model": {"model": "gpt-5-mini", "temperature": 0.7},
        "testbed": {"judge_model": {"provider": "openai", "id": "gpt-5-mini"}},
        "vector_search": {
            "enabled": True,
            "vector_store": "ORACLE",
            "search_type": "Similarity",
            "alias": "mydb",
        },
        "database": {"alias": "mydb"},
    },
    "correctness": 0.85,
    "correct_by_topic": [{"topic": "T1", "correctness": 0.9}],
    "failures": [],
    "report": [{"question": "Q1", "answer": "A1"}],
}


# ---------------------------------------------------------------------------
# Module import helper — testbed.py calls main() at module level
# ---------------------------------------------------------------------------
def _mock_enabled_models(model_type):
    """Return different model dicts for ll vs embed lookups."""
    if model_type == "ll":
        return {"openai/m1": {"provider": "openai", "id": "m1"}}
    return {"openai/e1": {"provider": "openai", "id": "e1"}}


def _passthrough_cache(**_kw):
    """Replacement for st.cache_data that passes through with a .clear() stub."""

    def decorator(fn):
        fn.clear = lambda: None
        return fn

    return decorator


def _passthrough_decorator(*_a, **_kw):
    """Replacement for st.fragment / st.dialog that preserves __wrapped__."""

    def decorator(fn):
        fn.__wrapped__ = fn
        return fn

    return decorator


def _ensure_testbed_loaded():
    """Import testbed module once with module-level main() neutralised."""
    if "client.app.content.testbed" in sys.modules:
        return

    import streamlit as real_st

    import client.app.core.api  # noqa: F811
    import client.app.core.helpers  # noqa: F811
    import client.app.core.sidebar  # noqa: F811

    state = _make_state({"runtime_generate_test": False})

    def _make_cols(widths, **_kw):
        n = widths if isinstance(widths, int) else len(widths)
        cols = [MagicMock() for _ in range(n)]
        for c in cols:
            c.button.return_value = False
        return cols

    with ExitStack() as stack:
        enter = stack.enter_context
        # Streamlit session_state → our AttrDict
        enter(patch.object(real_st, "session_state", state))
        # Decorators → pass-throughs
        enter(patch.object(real_st, "cache_data", _passthrough_cache))
        enter(patch.object(real_st, "fragment", _passthrough_decorator))
        enter(patch.object(real_st, "dialog", _passthrough_decorator))
        # UI functions → no-ops / safe returns
        for attr in (
            "header",
            "subheader",
            "write",
            "info",
            "error",
            "warning",
            "success",
            "stop",
            "toggle",
            "text_input",
            "text_area",
            "download_button",
            "pyplot",
            "dataframe",
            "markdown",
        ):
            enter(patch.object(real_st, attr))
        enter(patch.object(real_st, "columns", side_effect=_make_cols))
        enter(patch.object(real_st, "radio", return_value="Local"))
        enter(patch.object(real_st, "file_uploader", return_value=[]))
        enter(patch.object(real_st, "selectbox", return_value=None))
        enter(patch.object(real_st, "number_input", return_value=2))
        # Helpers → mocked on source modules so testbed's `from ... import` picks up mocks
        enter(patch.object(client.app.core.helpers, "enabled_models_lookup", side_effect=_mock_enabled_models))
        enter(patch.object(client.app.core.helpers, "state_configs_lookup", return_value={"testdb": {"usable": True}}))
        enter(patch.object(client.app.core.helpers, "update_client_settings"))
        enter(patch.object(client.app.core.helpers, "selectbox_index", return_value=0))
        enter(patch.object(client.app.core.helpers, "unique_file_payload", return_value=[]))
        enter(patch.object(client.app.core.api, "api_get", return_value=[]))
        enter(patch.object(client.app.core.api, "api_post", return_value={}))
        enter(patch.object(client.app.core.api, "api_delete"))
        # Sidebar → no-ops
        enter(patch.object(client.app.core.sidebar, "toolkit_sidebar"))
        enter(patch.object(client.app.core.sidebar, "lm_sidebar"))
        enter(patch.object(client.app.core.sidebar, "vector_search_sidebar"))

        import client.app.content.testbed  # noqa: F401


_ensure_testbed_loaded()


# ---------------------------------------------------------------------------
# _model_identity_to_key — pure function
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "identity,expected",
    [
        ({"provider": "openai", "id": "gpt-5-mini"}, "openai/gpt-5-mini"),
        (None, None),
        ({}, None),
        ({"id": "gpt-5-mini"}, None),
        ({"provider": "openai"}, None),
        ({"provider": "", "id": "gpt-5-mini"}, None),
    ],
    ids=["valid", "none", "empty", "missing_provider", "missing_id", "empty_provider"],
)
def test_model_identity_to_key(identity, expected):
    """_model_identity_to_key returns 'provider/id' or None for falsy/missing inputs."""
    from client.app.content.testbed import _model_identity_to_key

    assert _model_identity_to_key(identity) == expected


# ---------------------------------------------------------------------------
# TestIsDbConfigured
# ---------------------------------------------------------------------------
class TestIsDbConfigured:
    """Tests for _is_db_configured."""

    def test_returns_true_when_db_usable(self):
        """Returns True when alias maps to a usable database."""
        from client.app.content.testbed import _is_db_configured

        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.state_configs_lookup", return_value={"testdb": {"usable": True}}),
        ):
            assert _is_db_configured() is True

    def test_returns_false_when_no_alias(self):
        """Returns False when database alias is empty."""
        from client.app.content.testbed import _is_db_configured

        state = _make_state()
        state["settings"]["client_settings"]["database"] = {"alias": ""}
        with patch(f"{MODULE}.state", state):
            assert _is_db_configured() is False

    def test_returns_false_when_no_database_key(self):
        """Returns False when no database key in client_settings."""
        from client.app.content.testbed import _is_db_configured

        state = _make_state()
        state["settings"]["client_settings"] = {}
        with patch(f"{MODULE}.state", state):
            assert _is_db_configured() is False

    def test_returns_false_when_alias_not_in_lookup(self):
        """Returns False when alias not found in config lookup."""
        from client.app.content.testbed import _is_db_configured

        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.state_configs_lookup", return_value={}),
        ):
            assert _is_db_configured() is False

    def test_returns_false_when_not_usable(self):
        """Returns False when database exists but usable is False."""
        from client.app.content.testbed import _is_db_configured

        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.state_configs_lookup", return_value={"testdb": {"usable": False}}),
        ):
            assert _is_db_configured() is False


# ---------------------------------------------------------------------------
# TestSyncTestbedModel
# ---------------------------------------------------------------------------
class TestSyncTestbedModel:
    """Tests for _sync_testbed_model."""

    def test_persists_model_selection(self):
        """Splits value and calls update_client_settings with correct structure."""
        from client.app.content.testbed import _sync_testbed_model

        state = _make_state({"wk": "openai/gpt-5-mini"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            _sync_testbed_model("judge_model", "wk")
            mock_update.assert_called_once_with(
                {"testbed": {"judge_model": {"provider": "openai", "id": "gpt-5-mini"}}}
            )

    def test_no_value_skips(self):
        """Does nothing when widget key has no value."""
        from client.app.content.testbed import _sync_testbed_model

        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            _sync_testbed_model("judge_model", "missing_key")
            mock_update.assert_not_called()

    def test_no_slash_skips(self):
        """Does nothing when value has no slash."""
        from client.app.content.testbed import _sync_testbed_model

        state = _make_state({"wk": "noslash"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            _sync_testbed_model("judge_model", "wk")
            mock_update.assert_not_called()

    def test_multi_slash_splits_on_first(self):
        """Splits only on the first slash."""
        from client.app.content.testbed import _sync_testbed_model

        state = _make_state({"wk": "oci/cohere/embed-v3"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            _sync_testbed_model("qa_ll_model", "wk")
            mock_update.assert_called_once_with(
                {"testbed": {"qa_ll_model": {"provider": "oci", "id": "cohere/embed-v3"}}}
            )


# ---------------------------------------------------------------------------
# TestResetTestset
# ---------------------------------------------------------------------------
class TestResetTestset:
    """Tests for _reset_testset."""

    def test_clears_state_keys(self):
        """Removes all four runtime testbed keys from state."""
        from client.app.content.testbed import _reset_testset

        state = _make_state(
            {
                "runtime_testbed": {},
                "runtime_testbed_qa": [],
                "runtime_testbed_db_testsets": [],
                "runtime_testbed_evaluations": [],
            }
        )
        mock_cache = MagicMock()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            _reset_testset()
        assert "runtime_testbed" not in state
        assert "runtime_testbed_qa" not in state
        assert "runtime_testbed_db_testsets" not in state
        assert "runtime_testbed_evaluations" not in state

    def test_missing_keys_no_error(self):
        """No KeyError when keys are already absent."""
        from client.app.content.testbed import _reset_testset

        state = _make_state()
        mock_cache = MagicMock()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            _reset_testset()

    def test_cache_false_does_not_clear(self):
        """cache=False does not call .clear() on the cached function."""
        from client.app.content.testbed import _reset_testset

        state = _make_state()
        mock_cache = MagicMock()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            _reset_testset(cache=False)
        mock_cache.clear.assert_not_called()

    def test_cache_true_clears(self):
        """cache=True calls .clear() on the cached function."""
        from client.app.content.testbed import _reset_testset

        state = _make_state()
        mock_cache = MagicMock()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            _reset_testset(cache=True)
        mock_cache.clear.assert_called_once()


# ---------------------------------------------------------------------------
# TestGetTestbedDbTestsets
# ---------------------------------------------------------------------------
class TestGetTestbedDbTestsets:
    """Tests for _get_testbed_db_testsets."""

    def test_calls_api_get(self):
        """Delegates to api_get with correct path."""
        from client.app.content.testbed import _get_testbed_db_testsets

        expected = [{"tid": "t1", "name": "Set1"}]
        with patch(f"{MODULE}.api_get", return_value=expected) as mock_get:
            result = _get_testbed_db_testsets()
        assert result == expected
        mock_get.assert_called_once_with("testbed/testsets")


# ---------------------------------------------------------------------------
# TestUpdateRecord
# ---------------------------------------------------------------------------
class TestUpdateRecord:
    """Tests for _update_record (st.fragment decorated)."""

    def _call(self, state, direction=0):
        from client.app.content.testbed import _update_record

        with patch(f"{MODULE}.state", state):
            fn = getattr(_update_record, "__wrapped__", _update_record)
            fn(direction)

    def test_saves_and_stays(self):
        """direction=0 saves current record but does not change index."""
        state = _make_state(
            {
                "runtime_testbed": {"qa_index": 1},
                "runtime_testbed_qa": _qa_records(3),
                "runtime_q_1": "Updated Q",
                "runtime_a_1": "Updated A",
            }
        )
        self._call(state, 0)
        assert state["runtime_testbed"]["qa_index"] == 1
        assert state["runtime_testbed_qa"][1]["question"] == "Updated Q"
        assert state["runtime_testbed_qa"][1]["reference_answer"] == "Updated A"

    def test_navigates_forward(self):
        """direction=1 increments qa_index."""
        state = _make_state(
            {
                "runtime_testbed": {"qa_index": 0},
                "runtime_testbed_qa": _qa_records(3),
                "runtime_q_0": "Q0",
                "runtime_a_0": "A0",
            }
        )
        self._call(state, 1)
        assert state["runtime_testbed"]["qa_index"] == 1

    def test_navigates_backward(self):
        """direction=-1 decrements qa_index."""
        state = _make_state(
            {
                "runtime_testbed": {"qa_index": 2},
                "runtime_testbed_qa": _qa_records(3),
                "runtime_q_2": "Q2",
                "runtime_a_2": "A2",
            }
        )
        self._call(state, -1)
        assert state["runtime_testbed"]["qa_index"] == 1


# ---------------------------------------------------------------------------
# TestDeleteRecord
# ---------------------------------------------------------------------------
class TestDeleteRecord:
    """Tests for _delete_record (st.fragment decorated)."""

    def _call(self, state):
        from client.app.content.testbed import _delete_record

        with patch(f"{MODULE}.state", state):
            fn = getattr(_delete_record, "__wrapped__", _delete_record)
            fn()

    def test_deletes_middle_record(self):
        """Deleting record at index 1 of 3 keeps index at 1."""
        state = _make_state({"runtime_testbed": {"qa_index": 1}, "runtime_testbed_qa": _qa_records(3)})
        self._call(state)
        assert len(state["runtime_testbed_qa"]) == 2
        assert state["runtime_testbed"]["qa_index"] == 1

    def test_deletes_last_record_adjusts_index(self):
        """Deleting the last record adjusts index to new last."""
        state = _make_state({"runtime_testbed": {"qa_index": 2}, "runtime_testbed_qa": _qa_records(3)})
        self._call(state)
        assert len(state["runtime_testbed_qa"]) == 2
        assert state["runtime_testbed"]["qa_index"] == 1

    def test_deletes_only_record(self):
        """Deleting the sole record leaves empty list and index 0."""
        state = _make_state({"runtime_testbed": {"qa_index": 0}, "runtime_testbed_qa": _qa_records(1)})
        self._call(state)
        assert len(state["runtime_testbed_qa"]) == 0
        assert state["runtime_testbed"]["qa_index"] == 0

    def test_deletes_first_record(self):
        """Deleting first record of 3 keeps index at 0."""
        state = _make_state({"runtime_testbed": {"qa_index": 0}, "runtime_testbed_qa": _qa_records(3)})
        self._call(state)
        assert len(state["runtime_testbed_qa"]) == 2
        assert state["runtime_testbed"]["qa_index"] == 0


# ---------------------------------------------------------------------------
# TestQaDelete
# ---------------------------------------------------------------------------
class TestQaDelete:
    """Tests for _qa_delete."""

    def test_successful_delete(self):
        """Calls api_delete and resets testset on success."""
        from client.app.content.testbed import _qa_delete

        state = _make_state({"runtime_testbed": {"testset_id": "t1", "testset_name": "Set1"}})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_delete") as mock_del,
            patch(f"{MODULE}._reset_testset") as mock_reset,
            patch(f"{MODULE}.st"),
        ):
            _qa_delete()
        mock_del.assert_called_once()
        assert "testbed/testset_delete/t1" in mock_del.call_args[0][0]
        mock_reset.assert_called_once_with(True)

    def test_http_error_shows_error(self):
        """Shows st.error on HTTPStatusError."""
        from client.app.content.testbed import _qa_delete

        state = _make_state({"runtime_testbed": {"testset_id": "t1", "testset_name": "Set1"}})
        mock_st = MagicMock()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_delete", side_effect=make_http_error(404, "Not found")),
            patch(f"{MODULE}._reset_testset") as mock_reset,
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.extract_error_detail", return_value="Not found"),
        ):
            _qa_delete()
        mock_st.error.assert_called_once()
        assert "Failed to delete" in mock_st.error.call_args[0][0]
        mock_reset.assert_not_called()


# ---------------------------------------------------------------------------
# TestQaUpdateDb
# ---------------------------------------------------------------------------
class TestQaUpdateDb:
    """Tests for _qa_update_db."""

    def test_posts_qa_data(self):
        """Serialises Q&A, posts to API, and refreshes cache."""
        from client.app.content.testbed import _qa_update_db

        qa = _qa_records(2)
        mock_cache = MagicMock(return_value=[{"tid": "t1", "name": "Set1"}])
        state = _make_state(
            {
                "runtime_testbed": {"testset_id": "t1", "testset_name": "Set1"},
                "runtime_testbed_qa": qa,
                "runtime_new_testset_name": "Set1",
            }
        )
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_record"),
            patch(f"{MODULE}.api_post") as mock_post,
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            _qa_update_db()
        mock_post.assert_called_once()
        call_kw = mock_post.call_args[1] if mock_post.call_args[1] else {}
        call_args = mock_post.call_args[0] if mock_post.call_args[0] else ()
        # Endpoint
        assert (
            call_args[0] == "testbed/testset_load" if call_args else call_kw.get("endpoint") == "testbed/testset_load"
        )
        mock_cache.clear.assert_called_once()
        assert "runtime_testbed_db_testsets" in state


# ---------------------------------------------------------------------------
# TestQaUpdateGui
# ---------------------------------------------------------------------------
class TestQaUpdateGui:
    """Tests for _qa_update_gui."""

    def _call(self, state, mock_st):
        from client.app.content.testbed import _qa_update_gui

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_record"),
            patch(f"{MODULE}._delete_record"),
        ):
            _qa_update_gui(state["runtime_testbed_qa"])

    def test_renders_record_count(self):
        """Displays 'Record: 1/3' for first of three records."""
        state = _make_state({"runtime_testbed": {"qa_index": 0}, "runtime_testbed_qa": _qa_records(3)})
        mock_st = MagicMock()

        def _make_cols(widths, **_kw):
            n = widths if isinstance(widths, int) else len(widths)
            return [MagicMock() for _ in range(n)]

        mock_st.columns.side_effect = _make_cols
        self._call(state, mock_st)
        mock_st.write.assert_called_once_with("Record: 1/3")

    def test_prev_disabled_at_first(self):
        """Previous button disabled at index 0."""
        state = _make_state({"runtime_testbed": {"qa_index": 0}, "runtime_testbed_qa": _qa_records(3)})
        mock_st = MagicMock()
        cols = [MagicMock() for _ in range(4)]
        mock_st.columns.return_value = cols
        self._call(state, mock_st)
        prev_call = cols[0].button.call_args
        assert prev_call[1]["disabled"] is True

    def test_next_disabled_at_last(self):
        """Next button disabled at last index."""
        state = _make_state({"runtime_testbed": {"qa_index": 2}, "runtime_testbed_qa": _qa_records(3)})
        mock_st = MagicMock()
        cols = [MagicMock() for _ in range(4)]
        mock_st.columns.return_value = cols
        self._call(state, mock_st)
        next_call = cols[1].button.call_args
        assert next_call[1]["disabled"] is True

    def test_delete_disabled_single_record(self):
        """Delete button disabled when only one record."""
        state = _make_state({"runtime_testbed": {"qa_index": 0}, "runtime_testbed_qa": _qa_records(1)})
        mock_st = MagicMock()
        cols = [MagicMock() for _ in range(4)]
        mock_st.columns.return_value = cols
        self._call(state, mock_st)
        delete_call = cols[3].button.call_args
        assert delete_call[1]["disabled"] is True


# ---------------------------------------------------------------------------
# TestEvaluationReport — via __wrapped__
# ---------------------------------------------------------------------------
class TestEvaluationReport:
    """Tests for _evaluation_report (st.dialog decorated)."""

    def _call(self, mock_st, **kwargs):
        from client.app.content.testbed import _evaluation_report

        with patch(f"{MODULE}.st", mock_st):
            fn = getattr(_evaluation_report, "__wrapped__", _evaluation_report)
            fn(**kwargs)

    def test_fetches_report_by_eid(self):
        """Fetches report via api_get when eid is provided."""
        mock_st = MagicMock()
        with patch(f"{MODULE}.api_get", return_value=SAMPLE_REPORT) as mock_get:
            self._call(mock_st, eid="e1")
        mock_get.assert_called_once_with("testbed/evaluation", params={"eid": "e1"})

    def test_renders_with_provided_report(self):
        """Uses provided report dict without calling api_get."""
        mock_st = MagicMock()
        with patch(f"{MODULE}.api_get") as mock_get:
            self._call(mock_st, report=SAMPLE_REPORT)
        mock_get.assert_not_called()
        mock_st.subheader.assert_any_call("Evaluation Settings")
        figure = mock_st.pyplot.call_args.args[0]
        assert figure.axes[0].texts[-1].get_text() == "85%"
        assert mock_st.pyplot.call_args.kwargs == {"width": "stretch"}

    def test_no_report_shows_error(self):
        """Shows error when neither eid nor report provided."""
        mock_st = MagicMock()
        self._call(mock_st)
        mock_st.error.assert_called_once_with("No evaluation report available.")

    def test_judge_model_dict(self):
        """Formats judge model dict as 'provider/id'."""
        mock_st = MagicMock()
        with patch(f"{MODULE}.api_get"):
            self._call(mock_st, report=SAMPLE_REPORT)
        markdown_calls = [str(c) for c in mock_st.markdown.call_args_list]
        assert any("openai/gpt-5-mini" in c for c in markdown_calls)

    def test_judge_model_string(self):
        """Renders string judge model as-is."""
        mock_st = MagicMock()
        report = _deep_copy_report()
        report["settings"]["testbed"]["judge_model"] = "custom-judge"
        with patch(f"{MODULE}.api_get"):
            self._call(mock_st, report=report)
        markdown_calls = [str(c) for c in mock_st.markdown.call_args_list]
        assert any("custom-judge" in c for c in markdown_calls)

    def test_vector_search_disabled(self):
        """Shows 'without Vector Search' when VS disabled."""
        mock_st = MagicMock()
        report = _deep_copy_report()
        report["settings"]["vector_search"]["enabled"] = False
        with patch(f"{MODULE}.api_get"):
            self._call(mock_st, report=report)
        markdown_calls = [str(c) for c in mock_st.markdown.call_args_list]
        assert any("without Vector Search" in c for c in markdown_calls)

    def test_backward_compat_tools_enabled(self):
        """Falls back to tools_enabled list when enabled key is missing."""
        mock_st = MagicMock()
        report = _deep_copy_report()
        del report["settings"]["vector_search"]["enabled"]
        report["settings"]["tools_enabled"] = ["Vector Search"]
        with patch(f"{MODULE}.api_get"):
            self._call(mock_st, report=report)
        mock_st.subheader.assert_any_call("Vector Search Settings")

    def test_missing_vector_store_shows_unknown(self):
        """Old reports without vector_store key show 'Unknown' fallback."""
        mock_st = MagicMock()
        report = _deep_copy_report()
        del report["settings"]["vector_search"]["vector_store"]
        with patch(f"{MODULE}.api_get"):
            self._call(mock_st, report=report)
        markdown_calls = [str(c) for c in mock_st.markdown.call_args_list]
        assert any("Unspecified" in c for c in markdown_calls)

    def test_similarity_drops_extra_columns(self):
        """Similarity search type renders without error."""
        mock_st = MagicMock()
        report = _deep_copy_report()
        report["settings"]["vector_search"]["search_type"] = "Similarity"
        with patch(f"{MODULE}.api_get"):
            self._call(mock_st, report=report)
        # No assertion beyond "no exception raised"

    def test_string_correctness_is_rendered_as_percentage(self):
        """Numeric strings are converted before percentage calculation."""
        mock_st = MagicMock()
        report = _deep_copy_report()
        report["correctness"] = "0"
        report["correct_by_topic"] = [{"topic": "T1", "correctness": "0"}]

        self._call(mock_st, report=report)

        figure = mock_st.pyplot.call_args.args[0]
        topic_frame = next(
            call.args[0]
            for call in mock_st.dataframe.call_args_list
            if isinstance(call.args[0], pd.DataFrame) and "Correctness %" in call.args[0].columns
        )
        assert figure.axes[0].texts[-1].get_text() == "0%"
        assert topic_frame.loc[0, "Correctness %"] == 0


@pytest.mark.parametrize(("value", "expected"), [(-1, "0%"), (85.4, "85%"), (101, "100%")])
def test_create_gauge_clamps_percentage(value, expected):
    """Gauge values are constrained to the displayed percentage range."""
    from client.app.content.testbed import _create_gauge

    figure = _create_gauge(value)

    assert figure.axes[0].texts[-1].get_text() == expected
    assert len(figure.axes[0].patches) == 4


def _deep_copy_report():
    """Return a deep copy of SAMPLE_REPORT for mutation in tests."""
    import copy

    return copy.deepcopy(SAMPLE_REPORT)


# ---------------------------------------------------------------------------
# TestCheckPrerequisites
# ---------------------------------------------------------------------------
class TestCheckPrerequisites:
    """Tests for _check_prerequisites."""

    def test_all_available(self):
        """Returns models and gen_disabled=False when all prerequisites met."""
        from client.app.content.testbed import _check_prerequisites

        mock_st = MagicMock()
        with (
            patch(f"{MODULE}._is_db_configured", return_value=True),
            patch(f"{MODULE}.enabled_models_lookup", side_effect=_mock_enabled_models),
            patch(f"{MODULE}.st", mock_st),
        ):
            ll, embed, disabled = _check_prerequisites()
        assert ll == ["openai/m1"]
        assert embed == ["openai/e1"]
        assert disabled is False

    def test_no_db_calls_stop(self):
        """Calls st.stop when database is not configured."""
        from client.app.content.testbed import _check_prerequisites

        mock_st = MagicMock()
        mock_st.stop.side_effect = SystemExit
        with (
            patch(f"{MODULE}._is_db_configured", return_value=False),
            patch(f"{MODULE}.enabled_models_lookup", return_value={}),
            patch(f"{MODULE}.st", mock_st),
            pytest.raises(SystemExit),
        ):
            _check_prerequisites()
        mock_st.error.assert_called()
        mock_st.stop.assert_called_once()

    def test_no_ll_models_calls_stop(self):
        """Calls st.stop when no language models available."""
        from client.app.content.testbed import _check_prerequisites

        def _no_ll(t):
            return {} if t == "ll" else {"openai/e1": {"provider": "openai", "id": "e1"}}

        mock_st = MagicMock()
        mock_st.stop.side_effect = SystemExit
        with (
            patch(f"{MODULE}._is_db_configured", return_value=True),
            patch(f"{MODULE}.enabled_models_lookup", side_effect=_no_ll),
            patch(f"{MODULE}.st", mock_st),
            pytest.raises(SystemExit),
        ):
            _check_prerequisites()
        mock_st.stop.assert_called_once()

    def test_no_embed_models_disables_gen(self):
        """Returns gen_disabled=True when no embedding models available."""
        from client.app.content.testbed import _check_prerequisites

        def _no_embed(t):
            if t == "ll":
                return {"openai/m1": {"provider": "openai", "id": "m1"}}
            return {}

        mock_st = MagicMock()
        with (
            patch(f"{MODULE}._is_db_configured", return_value=True),
            patch(f"{MODULE}.enabled_models_lookup", side_effect=_no_embed),
            patch(f"{MODULE}.st", mock_st),
        ):
            _, embed, disabled = _check_prerequisites()
        assert disabled is True
        assert embed == []
        mock_st.warning.assert_called_once()

    def test_includes_oci_cohere_embed(self):
        """All enabled embed models are surfaced, including oci/cohere*.

        OCI Cohere embeddings now route via LiteLLM (and Giskard's LiteLLM
        embedding backend) — they are no longer filtered out.
        """
        from client.app.content.testbed import _check_prerequisites

        def _mixed_embed(t):
            if t == "ll":
                return {"openai/m1": {"provider": "openai", "id": "m1"}}
            return {
                "oci/cohere-v3": {"provider": "oci", "id": "cohere-v3"},
                "openai/embed": {"provider": "openai", "id": "embed"},
            }

        mock_st = MagicMock()
        with (
            patch(f"{MODULE}._is_db_configured", return_value=True),
            patch(f"{MODULE}.enabled_models_lookup", side_effect=_mixed_embed),
            patch(f"{MODULE}.st", mock_st),
        ):
            _, embed, _ = _check_prerequisites()
        assert "openai/embed" in embed
        assert "oci/cohere-v3" in embed


# ---------------------------------------------------------------------------
# TestSetupTestbedSources
# ---------------------------------------------------------------------------
class TestSetupTestbedSources:
    """Tests for _setup_testbed_sources."""

    def test_both_sources_when_db_testsets_exist(self):
        """Returns Database and Local when testsets exist."""
        from client.app.content.testbed import _setup_testbed_sources

        state = _make_state({"runtime_testbed_db_testsets": [{"tid": "t1"}]})
        with patch(f"{MODULE}.state", state):
            result = _setup_testbed_sources()
        assert result == ["Database", "Local"]

    def test_only_local_when_no_db_testsets(self):
        """Returns only Local when no database testsets."""
        from client.app.content.testbed import _setup_testbed_sources

        state = _make_state({"runtime_testbed_db_testsets": []})
        with patch(f"{MODULE}.state", state):
            result = _setup_testbed_sources()
        assert result == ["Local"]

    def test_fetches_testsets_if_not_in_state(self):
        """Fetches testsets from cache when key missing from state."""
        from client.app.content.testbed import _setup_testbed_sources

        state = _make_state()
        mock_cache = MagicMock(return_value=[])
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            result = _setup_testbed_sources()
        mock_cache.assert_called_once()
        assert "runtime_testbed_db_testsets" in state
        assert result == ["Local"]

    def test_503_sets_core_unavailable_and_warns(self):
        """A 503 from the testsets API sets _core_unavailable and shows a warning.

        The 503 must propagate from _get_testbed_db_testsets up to
        _setup_testbed_sources so the recovery flag is set and the UI
        shows a warning.  If the inner function swallows the 503 the
        flag is never set.
        """
        from client.app.content.testbed import _setup_testbed_sources

        state = _make_state()
        mock_st = MagicMock()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", side_effect=make_http_error(503, "CORE database is not available")),
        ):
            result = _setup_testbed_sources()
        assert state.get("_core_unavailable") is True
        assert result == ["Local"]
        mock_st.warning.assert_called_once()


# ---------------------------------------------------------------------------
# TestRenderTestsetGenerationUi
# ---------------------------------------------------------------------------
class TestRenderTestsetGenerationUi:
    """Tests for _render_testset_generation_ui."""

    def test_returns_params_dict(self):
        """Returns dict with expected keys."""
        from client.app.content.testbed import _render_testset_generation_ui

        mock_st = MagicMock()
        cols = [MagicMock() for _ in range(3)]
        mock_st.columns.return_value = cols
        cols[0].number_input.return_value = 5
        cols[1].selectbox.return_value = "openai/m1"
        cols[2].selectbox.return_value = "openai/e1"
        mock_st.file_uploader.return_value = []

        state = _make_state({"runtime_testbed": {"uploader_key": 1}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.selectbox_index", return_value=0),
            patch(f"{MODULE}._model_identity_to_key", return_value=None),
            patch(f"{MODULE}._sync_testbed_model"),
        ):
            result = _render_testset_generation_ui(["openai/m1"], ["openai/e1"])
        assert "ll_model" in result
        assert "embed_model" in result
        assert "questions" in result
        assert "upload_file" in result
        assert result["upload_file"] == []

    def test_accepts_multiple_files(self):
        """File uploader is configured to accept multiple PDF files."""
        from client.app.content.testbed import _render_testset_generation_ui

        mock_st = MagicMock()
        cols = [MagicMock() for _ in range(3)]
        mock_st.columns.return_value = cols
        cols[0].number_input.return_value = 5
        cols[1].selectbox.return_value = "openai/m1"
        cols[2].selectbox.return_value = "openai/e1"
        mock_st.file_uploader.return_value = [MagicMock()]

        state = _make_state({"runtime_testbed": {"uploader_key": 1}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.selectbox_index", return_value=0),
            patch(f"{MODULE}._model_identity_to_key", return_value=None),
            patch(f"{MODULE}._sync_testbed_model"),
        ):
            result = _render_testset_generation_ui(["openai/m1"], ["openai/e1"])
        mock_st.file_uploader.assert_called_once()
        call_kwargs = mock_st.file_uploader.call_args
        assert call_kwargs[1]["accept_multiple_files"] is True
        assert call_kwargs[1]["type"] == ["pdf"]
        assert len(result["upload_file"]) == 1

    def test_min_questions_scales_with_file_count(self):
        """Number input min_value equals the number of uploaded files."""
        from client.app.content.testbed import _render_testset_generation_ui

        mock_st = MagicMock()
        cols = [MagicMock() for _ in range(3)]
        mock_st.columns.return_value = cols
        cols[0].number_input.return_value = 5
        cols[1].selectbox.return_value = "openai/m1"
        cols[2].selectbox.return_value = "openai/e1"
        mock_st.file_uploader.return_value = [MagicMock() for _ in range(5)]

        state = _make_state({"runtime_testbed": {"uploader_key": 1}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.selectbox_index", return_value=0),
            patch(f"{MODULE}._model_identity_to_key", return_value=None),
            patch(f"{MODULE}._sync_testbed_model"),
        ):
            _render_testset_generation_ui(["openai/m1"], ["openai/e1"])
        call_kwargs = cols[0].number_input.call_args[1]
        assert call_kwargs["min_value"] == 5
        assert call_kwargs["max_value"] == 100

    def test_max_questions_scales_when_files_exceed_100(self):
        """max_value rises to match file count when more than 100 files uploaded."""
        from client.app.content.testbed import _render_testset_generation_ui

        mock_st = MagicMock()
        cols = [MagicMock() for _ in range(3)]
        mock_st.columns.return_value = cols
        cols[0].number_input.return_value = 101
        cols[1].selectbox.return_value = "openai/m1"
        cols[2].selectbox.return_value = "openai/e1"
        mock_st.file_uploader.return_value = [MagicMock() for _ in range(101)]

        state = _make_state({"runtime_testbed": {"uploader_key": 1}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.selectbox_index", return_value=0),
            patch(f"{MODULE}._model_identity_to_key", return_value=None),
            patch(f"{MODULE}._sync_testbed_model"),
        ):
            _render_testset_generation_ui(["openai/m1"], ["openai/e1"])
        call_kwargs = cols[0].number_input.call_args[1]
        assert call_kwargs["min_value"] == 101
        assert call_kwargs["max_value"] == 101


# ---------------------------------------------------------------------------
# TestRenderExistingTestsetUi
# ---------------------------------------------------------------------------
class TestRenderExistingTestsetUi:
    """Tests for _render_existing_testset_ui."""

    def test_local_source_returns_load_endpoint(self):
        """Local source returns testset_load endpoint with button disabled when no files."""
        from client.app.content.testbed import _render_existing_testset_ui

        mock_st = MagicMock()
        mock_st.radio.return_value = "Local"
        mock_st.file_uploader.return_value = []
        state = _make_state({"runtime_testbed": {"uploader_key": 1}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._reset_testset"),
        ):
            source, endpoint, disabled, tid = _render_existing_testset_ui(["Local"])
        assert source == "Local"
        assert endpoint == "testbed/testset_load"
        assert disabled is True
        assert tid is None

    def test_local_with_file_enables_button(self):
        """Button enabled when files are uploaded."""
        from client.app.content.testbed import _render_existing_testset_ui

        mock_st = MagicMock()
        mock_st.radio.return_value = "Local"
        mock_st.file_uploader.return_value = [MagicMock()]
        state = _make_state({"runtime_testbed": {"uploader_key": 1}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._reset_testset"),
        ):
            _, _, disabled, _ = _render_existing_testset_ui(["Local"])
        assert disabled is False

    def test_database_source_returns_qa_endpoint(self):
        """Database source returns testset_qa endpoint."""
        from client.app.content.testbed import _render_existing_testset_ui

        mock_st = MagicMock()
        mock_st.radio.return_value = "Database"
        mock_st.selectbox.return_value = None
        state = _make_state(
            {
                "runtime_testbed": {"uploader_key": 1},
                "runtime_testbed_db_testsets": [{"name": "S1", "created": "2026"}],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._reset_testset"),
        ):
            source, endpoint, disabled, _ = _render_existing_testset_ui(["Database", "Local"])
        assert source == "Database"
        assert endpoint == "testbed/testset_qa"
        assert disabled is True

    def test_database_extracts_testset_id(self):
        """Extracts testset_id when a database testset is selected."""
        from client.app.content.testbed import _render_existing_testset_ui

        mock_st = MagicMock()
        mock_st.radio.return_value = "Database"
        mock_st.selectbox.return_value = "Set1 -- Created: 2026-01-01"
        state = _make_state(
            {
                "runtime_testbed": {"uploader_key": 1},
                "runtime_testbed_db_testsets": [{"tid": "t1", "name": "Set1", "created": "2026-01-01"}],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._reset_testset"),
        ):
            _, _, disabled, tid = _render_existing_testset_ui(["Database", "Local"])
        assert tid == "t1"
        assert disabled is False


# ---------------------------------------------------------------------------
# TestProcessTestsetRequest
# ---------------------------------------------------------------------------
class TestProcessTestsetRequest:
    """Tests for _process_testset_request."""

    def test_none_endpoint_returns_early(self):
        """Returns immediately when endpoint is None."""
        from client.app.content.testbed import _process_testset_request

        with patch(f"{MODULE}.api_post") as mock_post:
            _process_testset_request(None, {})
        mock_post.assert_not_called()

    def test_local_load_posts_files(self):
        """Posts files for local testset load."""
        from client.app.content.testbed import _process_testset_request

        mock_st = MagicMock()
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_cache = MagicMock(return_value=[{"tid": "t1", "name": "TestSet"}])

        state = _make_state(
            {
                "runtime_testbed": {"testset_name": "TestSet", "uploader_key": 1},
                "runtime_uploader_1": [MagicMock()],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", return_value={"qa_data": _qa_records(2)}) as mock_post,
            patch(f"{MODULE}.unique_file_payload", return_value=[("files", ("f.json", b"[]", "application/json"))]),
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            _process_testset_request("testbed/testset_load", {}, "Local")
        mock_post.assert_called_once()
        assert state["runtime_testbed_qa"] == _qa_records(2)
        mock_st.success.assert_called_once()

    def test_generate_adds_model_params(self):
        """Includes ll_model, embed_model, questions in data for generation."""
        from client.app.content.testbed import _process_testset_request

        mock_st = MagicMock()
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_cache = MagicMock(return_value=[])

        state = _make_state(
            {
                "runtime_testbed": {"testset_name": "Gen", "uploader_key": 1},
                "runtime_uploader_1": MagicMock(),
                "optimizer_client": "cli",
            }
        )
        api_params = {"ll_model": "openai/m1", "embed_model": "openai/e1", "questions": 5}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", return_value={"qa_data": []}) as mock_post,
            patch(f"{MODULE}.unique_file_payload", return_value=[]),
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            _process_testset_request("testbed/testset_generate", api_params, None)
        call_kw = mock_post.call_args
        data = call_kw[1].get("data", call_kw[0][1] if len(call_kw[0]) > 1 else {})
        if isinstance(data, dict):
            assert data.get("ll_model") == "openai/m1"
            assert data.get("embed_model") == "openai/e1"

    def test_database_source_uses_api_get(self):
        """Uses api_get for Database source."""
        from client.app.content.testbed import _process_testset_request

        mock_st = MagicMock()
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        state = _make_state(
            {
                "runtime_testbed": {"testset_name": "DB", "uploader_key": 1},
                "runtime_db_testset": "Set1 -- Created: 2026-01-01",
                "runtime_testbed_db_testsets": [{"tid": "t1", "name": "Set1", "created": "2026-01-01"}],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", return_value={"qa_data": _qa_records(1)}) as mock_get,
        ):
            _process_testset_request("testbed/testset_qa", {}, "Database")
        mock_get.assert_called_once_with("testbed/testset_qa", params={"tid": "t1"})
        assert state["runtime_testbed_qa"] == _qa_records(1)

    def test_http_error_shows_error_and_stops(self):
        """Shows error and stops on HTTPStatusError."""
        from client.app.content.testbed import _process_testset_request

        mock_st = MagicMock()
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        state = _make_state(
            {
                "runtime_testbed": {"testset_name": "Err", "uploader_key": 1},
                "runtime_uploader_1": [],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.unique_file_payload", return_value=[]),
            patch(f"{MODULE}.api_post", side_effect=make_http_error(500, "Server error")),
            patch(f"{MODULE}.extract_error_detail", return_value="Server error"),
        ):
            _process_testset_request("testbed/testset_load", {}, "Local")
        mock_st.error.assert_called()
        mock_st.stop.assert_called()

    def test_data_error_shows_error_and_stops(self):
        """Shows error and stops on ValueError/KeyError/TypeError from malformed data."""
        from client.app.content.testbed import _process_testset_request

        mock_st = MagicMock()
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)

        state = _make_state(
            {
                "runtime_testbed": {"testset_name": "Err", "uploader_key": 1},
                "runtime_uploader_1": [],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.unique_file_payload", return_value=[]),
            patch(f"{MODULE}.api_post", side_effect=ValueError("bad data")),
        ):
            _process_testset_request("testbed/testset_load", {}, "Local")
        mock_st.error.assert_called()
        mock_st.stop.assert_called()

    def test_success_sets_qa_state(self):
        """Sets runtime_testbed_qa on success."""
        from client.app.content.testbed import _process_testset_request

        mock_st = MagicMock()
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_cache = MagicMock(return_value=[])
        qa = _qa_records(3)

        state = _make_state(
            {
                "runtime_testbed": {"testset_name": "OK", "uploader_key": 1},
                "runtime_uploader_1": [],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.unique_file_payload", return_value=[]),
            patch(f"{MODULE}.api_post", return_value={"qa_data": qa}),
            patch(f"{MODULE}._get_testbed_db_testsets", mock_cache),
        ):
            _process_testset_request("testbed/testset_load", {}, "Local")
        assert state["runtime_testbed_qa"] == qa
        mock_st.success.assert_called_once()


# ---------------------------------------------------------------------------
# TestRenderEvaluationUi
# ---------------------------------------------------------------------------
class TestRenderEvaluationUi:
    """Tests for _render_evaluation_ui."""

    def _make_eval_state(self, extra=None):
        """Build state with evaluation-related keys."""
        base = _make_state(
            {
                "runtime_testbed": {"testset_id": "t1", "testset_name": "Set1"},
                "runtime_new_testset_name": "Set1",
                "enable_client": True,
            }
        )
        if extra:
            base.update(extra)
        return base

    def test_fetches_evaluations_on_first_render(self):
        """Fetches evaluations from API when not in state."""
        from client.app.content.testbed import _render_evaluation_ui

        mock_st = MagicMock()

        def _make_cols(widths, **_kw):
            n = widths if isinstance(widths, int) else len(widths)
            cols = [MagicMock() for _ in range(n)]
            for c in cols:
                c.button.return_value = False
            return cols

        mock_st.columns.side_effect = _make_cols

        state = self._make_eval_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", return_value=[]) as mock_get,
            patch(f"{MODULE}.sidebar"),
            patch(f"{MODULE}.selectbox_index", return_value=0),
            patch(f"{MODULE}._model_identity_to_key", return_value=None),
            patch(f"{MODULE}._evaluation_report"),
            patch(f"{MODULE}._qa_update_db"),
        ):
            _render_evaluation_ui(["openai/m1"])
        mock_get.assert_called_once_with("testbed/evaluations", params={"tid": "t1"})

    def test_skips_fetch_when_no_testset_id(self):
        """Does not fetch evaluations when testset_id is None."""
        from client.app.content.testbed import _render_evaluation_ui

        mock_st = MagicMock()

        def _make_cols(widths, **_kw):
            n = widths if isinstance(widths, int) else len(widths)
            cols = [MagicMock() for _ in range(n)]
            for c in cols:
                c.button.return_value = False
            return cols

        mock_st.columns.side_effect = _make_cols

        state = self._make_eval_state({"runtime_testbed": {"testset_id": None, "testset_name": "X"}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get") as mock_get,
            patch(f"{MODULE}.sidebar"),
            patch(f"{MODULE}.selectbox_index", return_value=0),
            patch(f"{MODULE}._model_identity_to_key", return_value=None),
            patch(f"{MODULE}._evaluation_report"),
            patch(f"{MODULE}._qa_update_db"),
        ):
            _render_evaluation_ui(["openai/m1"])
        mock_get.assert_not_called()

    def test_renders_previous_evaluations(self):
        """Renders previous evaluations section when data exists."""
        from client.app.content.testbed import _render_evaluation_ui

        mock_st = MagicMock()

        def _make_cols(widths, **_kw):
            n = widths if isinstance(widths, int) else len(widths)
            cols = [MagicMock() for _ in range(n)]
            for c in cols:
                c.button.return_value = False
                c.selectbox.return_value = None
            return cols

        mock_st.columns.side_effect = _make_cols

        evals = [{"eid": "e1", "evaluated": "2026-01-01", "correctness": 0.9}]
        state = self._make_eval_state({"runtime_testbed_evaluations": evals})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get"),
            patch(f"{MODULE}.sidebar"),
            patch(f"{MODULE}.selectbox_index", return_value=0),
            patch(f"{MODULE}._model_identity_to_key", return_value=None),
            patch(f"{MODULE}._evaluation_report"),
            patch(f"{MODULE}._qa_update_db"),
        ):
            _render_evaluation_ui(["openai/m1"])
        subheader_calls = [str(c) for c in mock_st.subheader.call_args_list]
        assert any("Previous Evaluations" in c for c in subheader_calls)

    def test_renders_sidebar_components(self):
        """Calls all three sidebar functions."""
        from client.app.content.testbed import _render_evaluation_ui

        mock_st = MagicMock()

        def _make_cols(widths, **_kw):
            n = widths if isinstance(widths, int) else len(widths)
            cols = [MagicMock() for _ in range(n)]
            for c in cols:
                c.button.return_value = False
            return cols

        mock_st.columns.side_effect = _make_cols

        state = self._make_eval_state()
        mock_sidebar = MagicMock()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", return_value=[]),
            patch(f"{MODULE}.sidebar", mock_sidebar),
            patch(f"{MODULE}.selectbox_index", return_value=0),
            patch(f"{MODULE}._model_identity_to_key", return_value=None),
            patch(f"{MODULE}._evaluation_report"),
            patch(f"{MODULE}._qa_update_db"),
        ):
            _render_evaluation_ui(["openai/m1"])
        mock_sidebar.toolkit_sidebar.assert_called_once()
        mock_sidebar.lm_sidebar.assert_called_once()
        mock_sidebar.vector_search_sidebar.assert_called_once()


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------
class TestMain:
    """Tests for main() entry point."""

    def _call(self, state, mock_st, **extra_patches):
        from client.app.content.testbed import main

        def _make_cols(widths, **_kw):
            n = widths if isinstance(widths, int) else len(widths)
            cols = [MagicMock() for _ in range(n)]
            for c in cols:
                c.button.return_value = False
            return cols

        mock_st.columns.side_effect = _make_cols

        replacements = {
            f"{MODULE}._check_prerequisites": MagicMock(return_value=(["openai/m1"], ["openai/e1"], False)),
            f"{MODULE}._setup_testbed_sources": MagicMock(return_value=["Local"]),
            f"{MODULE}._render_existing_testset_ui": MagicMock(
                return_value=("Local", "testbed/testset_load", True, None)
            ),
            f"{MODULE}._render_testset_generation_ui": MagicMock(
                return_value={"ll_model": "m", "embed_model": "e", "questions": 2, "upload_file": None}
            ),
            f"{MODULE}._process_testset_request": MagicMock(),
            f"{MODULE}._render_evaluation_ui": MagicMock(),
            f"{MODULE}._qa_update_gui": MagicMock(),
            f"{MODULE}._qa_update_db": MagicMock(),
            f"{MODULE}._qa_delete": MagicMock(),
            f"{MODULE}._reset_testset": MagicMock(),
            f"{MODULE}.pd": MagicMock(),
        }
        replacements.update(extra_patches)

        with ExitStack() as stack:
            stack.enter_context(patch(f"{MODULE}.st", mock_st))
            stack.enter_context(patch(f"{MODULE}.state", state))
            for k, v in replacements.items():
                stack.enter_context(patch(k, v))
            main()

    def test_initializes_testbed_state(self):
        """Creates runtime_testbed when missing from state."""
        mock_st = MagicMock()
        state = _make_state({"runtime_generate_test": False})
        self._call(state, mock_st)
        assert "runtime_testbed" in state
        assert "uploader_key" in state["runtime_testbed"]
        assert "qa_index" in state["runtime_testbed"]

    def test_skips_init_if_state_exists(self):
        """Preserves existing runtime_testbed."""
        mock_st = MagicMock()
        original = {"uploader_key": 42, "qa_index": 5, "testset_id": "old", "testset_name": "kept"}
        state = _make_state({"runtime_testbed": original, "runtime_generate_test": False})
        self._call(state, mock_st)
        assert state["runtime_testbed"]["uploader_key"] == 42

    def test_generate_off_renders_existing_ui(self):
        """Calls _render_existing_testset_ui when toggle is off."""
        mock_st = MagicMock()
        state = _make_state({"runtime_generate_test": False})
        mock_existing = MagicMock(return_value=("Local", "testbed/testset_load", True, None))
        self._call(state, mock_st, **{f"{MODULE}._render_existing_testset_ui": mock_existing})
        mock_existing.assert_called_once()

    def test_generate_on_renders_generation_ui(self):
        """Calls _render_testset_generation_ui when toggle is on."""
        mock_st = MagicMock()
        state = _make_state({"runtime_generate_test": True})
        mock_gen = MagicMock(return_value={"ll_model": "m", "embed_model": "e", "questions": 2, "upload_file": []})
        self._call(state, mock_st, **{f"{MODULE}._render_testset_generation_ui": mock_gen})
        mock_gen.assert_called_once()

    def test_qa_loaded_renders_editor(self):
        """Renders Q&A editor and evaluation UI when QA is loaded."""
        mock_st = MagicMock()
        state = _make_state(
            {
                "runtime_generate_test": False,
                "runtime_testbed_qa": _qa_records(2),
                "runtime_testbed": {"uploader_key": 1, "qa_index": 0, "testset_id": "t1", "testset_name": "S1"},
                "runtime_new_testset_name": "S1",
            }
        )
        mock_gui = MagicMock()
        mock_eval = MagicMock()
        self._call(
            state,
            mock_st,
            **{f"{MODULE}._qa_update_gui": mock_gui, f"{MODULE}._render_evaluation_ui": mock_eval},
        )
        mock_gui.assert_called_once()
        mock_eval.assert_called_once()

    def test_qa_not_loaded_skips_editor(self):
        """Skips Q&A editor when no QA data loaded."""
        mock_st = MagicMock()
        state = _make_state({"runtime_generate_test": False})
        mock_gui = MagicMock()
        self._call(state, mock_st, **{f"{MODULE}._qa_update_gui": mock_gui})
        mock_gui.assert_not_called()
