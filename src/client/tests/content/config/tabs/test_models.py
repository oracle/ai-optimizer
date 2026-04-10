"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.config.tabs.models
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

import httpx
import pytest

from client.tests.conftest import AttrDict, Rerun

MODULE = "client.app.content.config.tabs.models"
HELPERS_MODULE = "client.app.core.helpers"

_OPTIMIZER_HELP = AttrDict(
    {
        "optimizer_help": {
            "model_provider": "help:provider",
            "model_id": "help:model_id",
            "model_url": "help:url",
            "model_api_key": "help:api_key",
            "max_input_tokens": "help:max_input",
            "max_tokens": "help:max_tokens",
            "chunk_size": "help:chunk_size",
        }
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_model_state():
    """Factory fixture: build an AttrDict mimicking Streamlit session_state for models."""

    def _make(model_configs=None, ll_model=None, vector_search=None, testbed=None, extra=None):
        """Return an AttrDict with the given model-related settings."""
        data = AttrDict(
            {
                "settings": {
                    "model_configs": model_configs or [],
                    "client_settings": {
                        "ll_model": ll_model or {},
                        "vector_search": vector_search or {},
                        "testbed": testbed or {},
                    },
                },
            }
        )
        if extra:
            data.update(extra)
        return data

    return _make


# ---------------------------------------------------------------------------
# _model_configs_lookup
# ---------------------------------------------------------------------------


class TestModelConfigsLookup:
    """Test _model_configs_lookup helper."""

    def test_returns_matching_type_keyed_by_provider_id(self, make_model_state):
        """Only configs matching the type are returned, keyed by 'provider/id'."""
        from client.app.content.config.tabs.models import _model_configs_lookup

        configs = [
            {"id": "gpt-4o", "provider": "openai", "type": "ll"},
            {"id": "embed-v3", "provider": "cohere", "type": "embed"},
            {"id": "llama3", "provider": "ollama", "type": "ll"},
        ]
        state = make_model_state(model_configs=configs)
        with patch(f"{MODULE}.state", state):
            result = _model_configs_lookup("ll")

        assert "openai/gpt-4o" in result
        assert "ollama/llama3" in result
        assert "cohere/embed-v3" not in result

    def test_returns_empty_when_no_match(self, make_model_state):
        """Empty dict returned when no configs match the type."""
        from client.app.content.config.tabs.models import _model_configs_lookup

        configs = [{"id": "gpt-4o", "provider": "openai", "type": "ll"}]
        state = make_model_state(model_configs=configs)
        with patch(f"{MODULE}.state", state):
            result = _model_configs_lookup("embed")

        assert result == {}

    def test_returns_empty_for_empty_configs(self, make_model_state):
        """Empty dict returned when model_configs list is empty."""
        from client.app.content.config.tabs.models import _model_configs_lookup

        state = make_model_state()
        with patch(f"{MODULE}.state", state):
            result = _model_configs_lookup("ll")

        assert result == {}


# ---------------------------------------------------------------------------
# _fetch_model
# ---------------------------------------------------------------------------


class TestFetchModel:
    """Test _fetch_model helper."""

    def test_returns_config_on_success(self):
        """Successful GET returns the model config dict."""
        from client.app.content.config.tabs.models import _fetch_model

        expected = {"id": "gpt-4o", "provider": "openai", "api_key": "sk-123"}
        with patch(f"{MODULE}.api_get", return_value=expected):
            result = _fetch_model("openai", "gpt-4o")

        assert result == expected

    def test_returns_none_on_http_error(self):
        """HTTPStatusError is caught and None returned."""
        from client.app.content.config.tabs.models import _fetch_model

        mock_resp = MagicMock(status_code=404)
        error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_resp)
        with patch(f"{MODULE}.api_get", side_effect=error):
            result = _fetch_model("openai", "MISSING")

        assert result is None

    def test_url_encodes_model_id(self):
        """model_id with slashes is percent-encoded in the URL."""
        from client.app.content.config.tabs.models import _fetch_model

        with patch(f"{MODULE}.api_get", return_value={}) as mock_get:
            _fetch_model("hosted_vllm", "meta-llama/Llama-3.2")

        mock_get.assert_called_once_with(
            "models/hosted_vllm/meta-llama%2FLlama-3.2",
            params={"include_sensitive": "true"},
        )


# ---------------------------------------------------------------------------
# _get_supported_models
# ---------------------------------------------------------------------------


class TestGetSupportedModels:
    """Test _get_supported_models helper."""

    def test_returns_list_on_success(self):
        """Successful GET returns the provider list."""
        from client.app.content.config.tabs.models import _get_supported_models

        expected = [{"provider": "openai", "ids": [{"key": "gpt-4o"}]}]
        with patch(f"{MODULE}.api_get", return_value=expected):
            result = _get_supported_models("ll")

        assert result == expected

    def test_returns_empty_list_on_http_error(self):
        """HTTPStatusError is caught and empty list returned."""
        from client.app.content.config.tabs.models import _get_supported_models

        mock_resp = MagicMock(status_code=500)
        error = httpx.HTTPStatusError("Server error", request=MagicMock(), response=mock_resp)
        with patch(f"{MODULE}.api_get", side_effect=error):
            result = _get_supported_models("ll")

        assert result == []


# ---------------------------------------------------------------------------
# _clear_client_models
# ---------------------------------------------------------------------------


class TestClearClientModels:
    """Test _clear_client_models helper."""

    def test_clears_ll_model_on_match(self, make_model_state):
        """ll_model provider/id are set to None when they match."""
        from client.app.content.config.tabs.models import _clear_client_models

        state = make_model_state(ll_model={"provider": "openai", "id": "gpt-4o"})
        with patch(f"{MODULE}.state", state):
            _clear_client_models("openai", "gpt-4o")

        assert state["settings"]["client_settings"]["ll_model"]["id"] is None
        assert state["settings"]["client_settings"]["ll_model"]["provider"] is None

    def test_leaves_ll_model_on_mismatch(self, make_model_state):
        """ll_model is untouched when provider/id do not match."""
        from client.app.content.config.tabs.models import _clear_client_models

        state = make_model_state(ll_model={"provider": "openai", "id": "gpt-4o"})
        with patch(f"{MODULE}.state", state):
            _clear_client_models("anthropic", "sonnet")

        assert state["settings"]["client_settings"]["ll_model"]["id"] == "gpt-4o"
        assert state["settings"]["client_settings"]["ll_model"]["provider"] == "openai"

    def test_clears_vector_search_on_match(self, make_model_state):
        """vector_search id is set to None when it matches."""
        from client.app.content.config.tabs.models import _clear_client_models

        state = make_model_state(vector_search={"provider": "cohere", "id": "embed-v3"})
        with patch(f"{MODULE}.state", state):
            _clear_client_models("cohere", "embed-v3")

        assert state["settings"]["client_settings"]["vector_search"]["id"] is None

    def test_leaves_vector_search_on_mismatch(self, make_model_state):
        """vector_search is untouched when provider/id do not match."""
        from client.app.content.config.tabs.models import _clear_client_models

        state = make_model_state(vector_search={"provider": "cohere", "id": "embed-v3"})
        with patch(f"{MODULE}.state", state):
            _clear_client_models("openai", "text-embed")

        assert state["settings"]["client_settings"]["vector_search"]["id"] == "embed-v3"

    def test_clears_testbed_refs_on_match(self, make_model_state):
        """Matching testbed refs are set to None; non-matching refs stay."""
        from client.app.content.config.tabs.models import _clear_client_models

        tb = {
            "qa_ll_model": {"provider": "openai", "id": "gpt-4o"},
            "qa_embed_model": {"provider": "openai", "id": "gpt-4o"},
            "judge_model": {"provider": "anthropic", "id": "sonnet"},
        }
        state = make_model_state(testbed=tb)
        with patch(f"{MODULE}.state", state):
            _clear_client_models("openai", "gpt-4o")

        testbed = state["settings"]["client_settings"]["testbed"]
        assert testbed["qa_ll_model"] is None
        assert testbed["qa_embed_model"] is None
        assert testbed["judge_model"] == {"provider": "anthropic", "id": "sonnet"}

    def test_handles_already_none_testbed_keys(self, make_model_state):
        """Already-None testbed keys do not raise."""
        from client.app.content.config.tabs.models import _clear_client_models

        tb = {"qa_ll_model": None, "qa_embed_model": None, "judge_model": None}
        state = make_model_state(testbed=tb)
        with patch(f"{MODULE}.state", state):
            _clear_client_models("openai", "gpt-4o")

        testbed = state["settings"]["client_settings"]["testbed"]
        assert testbed["qa_ll_model"] is None


# ---------------------------------------------------------------------------
# _handle_form_submit
# ---------------------------------------------------------------------------


class TestHandleFormSubmit:
    """Test _handle_form_submit create and update paths."""

    def test_create_path_sets_provider_id_type(self, mock_st):
        """Create path writes provider, id, and type into form_data."""
        from client.app.content.config.tabs.models import _handle_form_submit

        form_data = {"api_base": "http://test"}
        mock_build = MagicMock(return_value=form_data)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_post") as mock_post,
        ):
            hlp.build_payload = mock_build
            result = _handle_form_submit("ll", True, "openai", "gpt-4o", form_data)

        assert result is True
        assert form_data["provider"] == "openai"
        assert form_data["id"] == "gpt-4o"
        assert form_data["type"] == "ll"
        mock_post.assert_called_once()

    def test_create_calls_api_post_with_toast(self, mock_st):
        """api_post is called with a toast containing provider/id."""
        from client.app.content.config.tabs.models import _handle_form_submit

        form_data = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_post") as mock_post,
        ):
            hlp.build_payload.return_value = form_data
            _handle_form_submit("ll", True, "openai", "gpt-4o", form_data)

        _, kwargs = mock_post.call_args
        assert "toast" in kwargs
        assert "openai/gpt-4o" in kwargs["toast"]

    def test_update_calls_api_put_with_encoded_id(self, mock_st):
        """Update path URL-encodes the model_id in the PUT path."""
        from client.app.content.config.tabs.models import _handle_form_submit

        form_data = {"enabled": True}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_put") as mock_put,
        ):
            hlp.build_payload.return_value = form_data
            _handle_form_submit("ll", False, "hosted_vllm", "meta-llama/Llama-3.2", form_data)

        mock_put.assert_called_once()
        path = mock_put.call_args.args[0]
        assert "meta-llama%2FLlama-3.2" in path

    def test_update_shows_toast(self, mock_st):
        """Update path calls st.toast with provider/id."""
        from client.app.content.config.tabs.models import _handle_form_submit

        form_data = {"enabled": True}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_put"),
        ):
            hlp.build_payload.return_value = form_data
            _handle_form_submit("ll", False, "openai", "gpt-4o", form_data)

        mock_st.toast.assert_called_once()
        assert "openai/gpt-4o" in mock_st.toast.call_args.args[0]

    def test_update_disabled_model_clears_client_models(self, mock_st):
        """Disabling a model calls _clear_client_models."""
        from client.app.content.config.tabs.models import _handle_form_submit

        form_data = {"enabled": False}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_put"),
            patch(f"{MODULE}._clear_client_models") as mock_clear,
        ):
            hlp.build_payload.return_value = form_data
            _handle_form_submit("ll", False, "openai", "gpt-4o", form_data)

        mock_clear.assert_called_once_with("openai", "gpt-4o")

    def test_update_enabled_model_does_not_clear(self, mock_st):
        """Enabling a model does not call _clear_client_models."""
        from client.app.content.config.tabs.models import _handle_form_submit

        form_data = {"enabled": True}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_put"),
            patch(f"{MODULE}._clear_client_models") as mock_clear,
        ):
            hlp.build_payload.return_value = form_data
            _handle_form_submit("ll", False, "openai", "gpt-4o", form_data)

        mock_clear.assert_not_called()

    def test_calls_refresh_settings(self, mock_st):
        """refresh_settings is called after a successful submit."""
        from client.app.content.config.tabs.models import _handle_form_submit

        form_data = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_post"),
        ):
            hlp.build_payload.return_value = form_data
            result = _handle_form_submit("ll", True, "openai", "gpt-4o", form_data)

        assert result is True
        hlp.refresh_settings.assert_called_once()

    def test_http_error_returns_false(self, mock_st):
        """HTTPStatusError is caught, st.error called, and False returned."""
        from client.app.content.config.tabs.models import _handle_form_submit

        mock_resp = MagicMock(status_code=409, content=b'{"detail":"conflict"}')
        mock_resp.json.return_value = {"detail": "conflict"}
        error = httpx.HTTPStatusError("Conflict", request=MagicMock(), response=mock_resp)

        form_data = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_post", side_effect=error),
        ):
            hlp.build_payload.return_value = form_data
            from client.app.core.helpers import extract_error_detail

            hlp.extract_error_detail.side_effect = extract_error_detail
            result = _handle_form_submit("ll", True, "openai", "gpt-4o", form_data)

        assert result is False
        mock_st.error.assert_called_once()


class TestNoChangeDetection:
    """No-change detection toasts when saving unchanged model configs."""

    def test_no_changes_shows_toast(self, mock_st):
        """Saving unchanged data on update shows 'No changes detected' toast."""
        from client.app.content.config.tabs.models import _handle_form_submit

        original = {"enabled": True, "api_base": "http://test", "api_key": "sk-123"}
        form_data = {"enabled": True, "api_base": "http://test", "api_key": "sk-123"}

        with patch(f"{MODULE}.st", mock_st):
            result = _handle_form_submit("ll", False, "openai", "gpt-4o", form_data, original_model=original)

        assert result is False
        mock_st.toast.assert_called_once()
        assert "No changes" in mock_st.toast.call_args[0][0]

    def test_changes_proceed_to_api(self, mock_st):
        """When form data differs from original, api_put is called."""
        from client.app.content.config.tabs.models import _handle_form_submit

        original = {"enabled": True, "api_base": "http://old"}
        form_data = {"enabled": False, "api_base": "http://new"}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_put") as mock_put,
            patch(f"{MODULE}._clear_client_models"),
        ):
            hlp.build_payload.return_value = form_data
            result = _handle_form_submit("ll", False, "openai", "gpt-4o", form_data, original_model=original)

        assert result is True
        mock_put.assert_called_once()

    def test_create_skips_no_change_check(self, mock_st):
        """Create path (is_new=True) skips the no-change detection."""
        from client.app.content.config.tabs.models import _handle_form_submit

        original = {"enabled": True}
        form_data = {"enabled": True}  # Same values but is_new=True

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_post") as mock_post,
        ):
            hlp.build_payload.return_value = form_data
            result = _handle_form_submit("ll", True, "openai", "gpt-4o", form_data, original_model=original)

        assert result is True
        mock_post.assert_called_once()

    def test_no_original_model_skips_check(self, mock_st):
        """When original_model is None, no-change check is skipped."""
        from client.app.content.config.tabs.models import _handle_form_submit

        form_data = {"enabled": True}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_put") as mock_put,
        ):
            hlp.build_payload.return_value = form_data
            result = _handle_form_submit("ll", False, "openai", "gpt-4o", form_data)

        assert result is True
        mock_put.assert_called_once()


# ---------------------------------------------------------------------------
# _remove_model
# ---------------------------------------------------------------------------


class TestRemoveModel:
    """Test _remove_model helper."""

    def test_success_returns_true(self, mock_st):
        """Successful delete clears refs, refreshes, and returns True."""
        from client.app.content.config.tabs.models import _remove_model

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_delete") as mock_delete,
            patch(f"{MODULE}._clear_client_models") as mock_clear,
            patch(f"{MODULE}.helpers") as hlp,
        ):
            result = _remove_model("openai", "gpt-4o")

        assert result is True
        mock_delete.assert_called_once()
        assert "gpt-4o" in mock_delete.call_args.args[0]
        mock_clear.assert_called_once_with("openai", "gpt-4o")
        hlp.refresh_settings.assert_called_once()

    def test_url_encodes_path(self, mock_st):
        """model_id with slashes is percent-encoded in the DELETE path."""
        from client.app.content.config.tabs.models import _remove_model

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_delete") as mock_delete,
            patch(f"{MODULE}._clear_client_models"),
            patch(f"{MODULE}.helpers"),
        ):
            _remove_model("hosted_vllm", "meta-llama/Llama-3.2")

        path = mock_delete.call_args.args[0]
        assert "meta-llama%2FLlama-3.2" in path

    def test_error_returns_false(self, mock_st):
        """HTTPStatusError is caught, st.error called, and False returned."""
        from client.app.content.config.tabs.models import _remove_model

        mock_resp = MagicMock(status_code=404, content=b'{"detail":"not found"}')
        mock_resp.json.return_value = {"detail": "not found"}
        error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_delete", side_effect=error),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            from client.app.core.helpers import extract_error_detail

            hlp.extract_error_detail.side_effect = extract_error_detail
            result = _remove_model("openai", "gpt-4o")

        assert result is False
        mock_st.error.assert_called_once()


# ---------------------------------------------------------------------------
# _initialize_model
# ---------------------------------------------------------------------------


class TestInitializeModel:
    """Test _initialize_model helper."""

    def test_edit_fetches_model(self, mock_st):
        """Edit action fetches the model via _fetch_model."""
        from client.app.content.config.tabs.models import _initialize_model

        fetched = {"id": "gpt-4o", "provider": "openai", "enabled": True}
        mock_st.checkbox.return_value = True

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._fetch_model", return_value=fetched) as mock_fetch,
        ):
            result = _initialize_model("edit", "ll", "gpt-4o", "openai")

        mock_fetch.assert_called_once_with("openai", "gpt-4o")
        assert result["id"] == "gpt-4o"

    def test_edit_falls_back_to_empty_dict(self, mock_st):
        """Edit action falls back to {} when fetch returns None."""
        from client.app.content.config.tabs.models import _initialize_model

        mock_st.checkbox.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._fetch_model", return_value=None),
        ):
            result = _initialize_model("edit", "ll", "gpt-4o", "openai")

        assert result == {"enabled": False}

    def test_add_returns_default_dict(self, mock_st):
        """Add action returns a default dict with enabled=True."""
        from client.app.content.config.tabs.models import _initialize_model

        with patch(f"{MODULE}.st", mock_st):
            result = _initialize_model("add", "ll", None, None)

        assert result["enabled"] is True
        assert result["type"] == "ll"

    def test_add_does_not_fetch(self, mock_st):
        """Add action does not call _fetch_model."""
        from client.app.content.config.tabs.models import _initialize_model

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._fetch_model") as mock_fetch,
        ):
            _initialize_model("add", "embed", None, None)

        mock_fetch.assert_not_called()

    def test_edit_renders_checkbox(self, mock_st):
        """Edit action renders an Enabled checkbox."""
        from client.app.content.config.tabs.models import _initialize_model

        mock_st.checkbox.return_value = True

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._fetch_model", return_value={"enabled": False}),
        ):
            _initialize_model("edit", "ll", "gpt-4o", "openai")

        mock_st.checkbox.assert_called_once()


# ---------------------------------------------------------------------------
# _render_provider_selection
# ---------------------------------------------------------------------------


class TestRenderProviderSelection:
    """Test _render_provider_selection helper."""

    def test_returns_provider_models(self, mock_st):
        """Returns the ids list for the selected provider."""
        from client.app.content.config.tabs.models import _render_provider_selection

        model = {"provider": "openai"}
        supported = [
            {"provider": "openai", "ids": [{"key": "gpt-4o"}]},
            {"provider": "anthropic", "ids": [{"key": "sonnet"}]},
        ]
        mock_st.selectbox.return_value = "openai"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            result_model, provider_models, _ = _render_provider_selection(model, supported, "add")

        assert provider_models == [{"key": "gpt-4o"}]

    def test_selectbox_disabled_on_edit(self, mock_st):
        """Provider selectbox is disabled in edit mode."""
        from client.app.content.config.tabs.models import _render_provider_selection

        model = {"provider": "openai"}
        supported = [{"provider": "openai", "ids": []}]
        mock_st.selectbox.return_value = "openai"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            _render_provider_selection(model, supported, "edit")

        _, kwargs = mock_st.selectbox.call_args
        assert kwargs["disabled"] is True

    def test_oci_flag_set_when_provider_is_oci(self, mock_st):
        """disable_for_oci is True when provider is 'oci'."""
        from client.app.content.config.tabs.models import _render_provider_selection

        model = {"provider": "oci"}
        supported = [{"provider": "oci", "ids": []}]
        mock_st.selectbox.return_value = "oci"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            _, _, disable_for_oci = _render_provider_selection(model, supported, "add")

        assert disable_for_oci is True


# ---------------------------------------------------------------------------
# _render_model_selection
# ---------------------------------------------------------------------------


class TestRenderModelSelection:
    """Test _render_model_selection helper."""

    def test_appends_unknown_model_id(self, mock_st):
        """Unknown model_id is appended to the selectbox options."""
        from client.app.content.config.tabs.models import _render_model_selection

        model = {"id": "custom-model", "provider": "openai"}
        provider_models = [{"key": "gpt-4o"}, {"key": "gpt-3.5"}]
        mock_st.selectbox.return_value = "custom-model"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            _render_model_selection(model, provider_models, "edit")

        _, kwargs = mock_st.selectbox.call_args
        assert "custom-model" in kwargs["options"]

    def test_selectbox_disabled_on_edit(self, mock_st):
        """Model selectbox is disabled in edit mode."""
        from client.app.content.config.tabs.models import _render_model_selection

        model = {"id": "gpt-4o", "provider": "openai"}
        provider_models = [{"key": "gpt-4o"}]
        mock_st.selectbox.return_value = "gpt-4o"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            _render_model_selection(model, provider_models, "edit")

        _, kwargs = mock_st.selectbox.call_args
        assert kwargs["disabled"] is True

    def test_accept_new_options_enabled(self, mock_st):
        """accept_new_options is True on the model selectbox."""
        from client.app.content.config.tabs.models import _render_model_selection

        model = {"id": "gpt-4o", "provider": "openai"}
        provider_models = [{"key": "gpt-4o"}]
        mock_st.selectbox.return_value = "gpt-4o"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            _render_model_selection(model, provider_models, "add")

        _, kwargs = mock_st.selectbox.call_args
        assert kwargs["accept_new_options"] is True


# ---------------------------------------------------------------------------
# _render_api_configuration
# ---------------------------------------------------------------------------


class TestRenderApiConfiguration:
    """Test _render_api_configuration helper."""

    def test_renders_api_base_and_api_key(self, mock_st):
        """Two text_input widgets are rendered for api_base and api_key."""
        from client.app.content.config.tabs.models import _render_api_configuration

        model = {"id": "gpt-4o", "api_base": "http://test", "api_key": "sk-123"}
        mock_st.text_input.side_effect = ["http://test", "sk-123"]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            result = _render_api_configuration(model, [], False)

        assert mock_st.text_input.call_count == 2
        assert result["api_base"] == "http://test"
        assert result["api_key"] == "sk-123"

    def test_both_disabled_for_oci(self, mock_st):
        """Both text inputs are disabled when disable_for_oci is True."""
        from client.app.content.config.tabs.models import _render_api_configuration

        model = {"id": "x", "api_base": "", "api_key": ""}
        mock_st.text_input.side_effect = ["", ""]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            _render_api_configuration(model, [], True)

        for c in mock_st.text_input.call_args_list:
            assert c.kwargs.get("disabled") is True

    def test_uses_litellm_api_base_as_default(self, mock_st):
        """LiteLLM api_base is used as the default value when available."""
        from client.app.content.config.tabs.models import _render_api_configuration

        model = {"id": "gpt-4o"}
        provider_models = [{"key": "gpt-4o", "api_base": "https://litellm-default.com"}]
        mock_st.text_input.side_effect = ["https://litellm-default.com", ""]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            _render_api_configuration(model, provider_models, False)

        first_call = mock_st.text_input.call_args_list[0]
        assert first_call.kwargs["value"] == "https://litellm-default.com"


# ---------------------------------------------------------------------------
# _render_model_specific_config
# ---------------------------------------------------------------------------


class TestRenderModelSpecificConfig:
    """Test _render_model_specific_config helper."""

    def test_ll_renders_max_input_tokens_and_max_tokens(self, mock_st):
        """Language model type renders two number inputs."""
        from client.app.content.config.tabs.models import _render_model_specific_config

        model = {"id": "gpt-4o", "max_input_tokens": 128000, "max_tokens": 4096}
        mock_st.number_input.side_effect = [128000, 4096]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            result = _render_model_specific_config(model, "ll", [])

        assert mock_st.number_input.call_count == 2
        assert result["max_input_tokens"] == 128000
        assert result["max_tokens"] == 4096

    def test_embed_renders_max_chunk_size(self, mock_st):
        """Embedding model type renders one number input for chunk size."""
        from client.app.content.config.tabs.models import _render_model_specific_config

        model = {"id": "embed-v3", "max_chunk_size": 512}
        mock_st.number_input.return_value = 512

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            result = _render_model_specific_config(model, "embed", [])

        assert mock_st.number_input.call_count == 1
        assert result["max_chunk_size"] == 512

    def test_embed_uses_provider_default_when_missing(self, mock_st):
        """Embed type pulls default chunk size from provider listing."""
        from client.app.content.config.tabs.models import _render_model_specific_config

        model = {"id": "embed-v3"}
        provider_models = [{"key": "embed-v3", "max_chunk_size": 2048}]
        mock_st.number_input.return_value = 2048

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", _OPTIMIZER_HELP):
            result = _render_model_specific_config(model, "embed", provider_models)

        assert mock_st.number_input.call_count == 1
        assert mock_st.number_input.call_args.kwargs["value"] == 2048
        assert result["max_chunk_size"] == 2048


# ---------------------------------------------------------------------------
# _handle_dialog_submission
# ---------------------------------------------------------------------------


class TestHandleDialogSubmission:
    """Test _handle_dialog_submission helper."""

    def _make_mock_st(self):
        """Return a MagicMock for st with a 3-column layout."""
        mock_st = MagicMock()
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        return mock_st

    def test_add_missing_id_shows_error(self):
        """Add with empty id and provider shows two error messages."""
        from client.app.content.config.tabs.models import _handle_dialog_submission

        mock_st = self._make_mock_st()
        action_btn = mock_st.columns.return_value[0]
        action_btn.button.return_value = True
        mock_st.columns.return_value[2].button.return_value = False

        model = {"id": "", "provider": ""}
        with patch(f"{MODULE}.st", mock_st):
            result = _handle_dialog_submission(model, "ll", "add")

        assert result is False
        assert mock_st.error.call_count == 2

    def test_add_missing_provider_shows_error(self):
        """Add with id but empty provider shows a provider error."""
        from client.app.content.config.tabs.models import _handle_dialog_submission

        mock_st = self._make_mock_st()
        action_btn = mock_st.columns.return_value[0]
        action_btn.button.return_value = True
        mock_st.columns.return_value[2].button.return_value = False

        model = {"id": "gpt-4o", "provider": ""}
        with patch(f"{MODULE}.st", mock_st):
            result = _handle_dialog_submission(model, "ll", "add")

        assert result is False
        error_messages = [c.args[0] for c in mock_st.error.call_args_list]
        assert any("Provider" in m for m in error_messages)

    def test_add_success_calls_handle_form_submit(self):
        """Successful add delegates to _handle_form_submit with is_new=True."""
        from client.app.content.config.tabs.models import _handle_dialog_submission

        mock_st = self._make_mock_st()
        action_btn = mock_st.columns.return_value[0]
        action_btn.button.return_value = True
        mock_st.columns.return_value[2].button.return_value = False

        model = {"id": "gpt-4o", "provider": "openai"}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._handle_form_submit", return_value=True) as mock_submit,
        ):
            result = _handle_dialog_submission(model, "ll", "add")

        assert result is True
        mock_submit.assert_called_once_with("ll", True, "openai", "gpt-4o", model)

    def test_edit_save_calls_handle_form_submit(self):
        """Save in edit mode delegates to _handle_form_submit with is_new=False."""
        from client.app.content.config.tabs.models import _handle_dialog_submission

        mock_st = self._make_mock_st()
        action_btn = mock_st.columns.return_value[0]
        action_btn.button.return_value = True
        mock_st.columns.return_value[2].button.return_value = False

        model = {"id": "gpt-4o", "provider": "openai"}
        original = {"id": "gpt-4o", "provider": "openai"}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._handle_form_submit", return_value=True) as mock_submit,
        ):
            result = _handle_dialog_submission(model, "ll", "edit", original_model=original)

        assert result is True
        mock_submit.assert_called_once_with("ll", False, "openai", "gpt-4o", model, original_model=original)

    def test_delete_calls_remove_model(self):
        """Delete button delegates to _remove_model."""
        from client.app.content.config.tabs.models import _handle_dialog_submission

        mock_st = self._make_mock_st()
        action_btn = mock_st.columns.return_value[0]
        action_btn.button.return_value = False
        delete_btn = mock_st.columns.return_value[1]
        delete_btn.button.return_value = True
        mock_st.columns.return_value[2].button.return_value = False

        model = {"id": "gpt-4o", "provider": "openai"}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._remove_model", return_value=True) as mock_remove,
        ):
            result = _handle_dialog_submission(model, "ll", "edit")

        assert result is True
        mock_remove.assert_called_once_with("openai", "gpt-4o")

    def test_cancel_calls_rerun(self):
        """Cancel button triggers st.rerun."""
        from client.app.content.config.tabs.models import _handle_dialog_submission

        mock_st = self._make_mock_st()
        mock_st.columns.return_value[0].button.return_value = False
        mock_st.columns.return_value[1].button.return_value = False
        cancel_btn = mock_st.columns.return_value[2]
        cancel_btn.button.return_value = True

        model = {"id": "gpt-4o", "provider": "openai"}
        with patch(f"{MODULE}.st", mock_st):
            result = _handle_dialog_submission(model, "ll", "edit")

        mock_st.rerun.assert_called_once()
        assert result is False

    def test_http_error_shows_error_message(self):
        """HTTPStatusError surfaces via st.error and returns False."""
        from client.app.content.config.tabs.models import _handle_dialog_submission

        mock_st = self._make_mock_st()
        action_btn = mock_st.columns.return_value[0]
        action_btn.button.return_value = True
        mock_st.columns.return_value[2].button.return_value = False

        error = httpx.HTTPStatusError(
            "Boom",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )

        model = {"id": "gpt-4o", "provider": "openai"}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._handle_form_submit", side_effect=error),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            from client.app.core.helpers import extract_error_detail

            hlp.extract_error_detail.side_effect = extract_error_detail
            result = _handle_dialog_submission(model, "ll", "add")

        mock_st.error.assert_called_once()
        assert result is False


# ---------------------------------------------------------------------------
# render_model_rows
# ---------------------------------------------------------------------------


class TestRenderModelRows:
    """Test render_model_rows display logic."""

    def test_renders_rows_only_for_matching_type(self, make_model_state, mock_st):
        """Only models matching the given type get a row."""
        from client.app.content.config.tabs.models import render_model_rows

        configs = [
            {"id": "gpt-4o", "provider": "openai", "type": "ll", "enabled": True, "api_base": "http://a"},
            {"id": "embed-v3", "provider": "cohere", "type": "embed", "enabled": False, "api_base": "http://b"},
        ]
        state = make_model_state(model_configs=configs)

        cols = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        mock_st.columns.side_effect = lambda widths, **kw: cols
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
        ):
            render_model_rows("ll")

        assert cols[3].button.call_count == 1

    def test_edit_button_kwargs(self, make_model_state, mock_st):
        """Edit button kwargs contain model_type, action, model_id, model_provider."""
        from client.app.content.config.tabs.models import render_model_rows

        configs = [
            {"id": "gpt-4o", "provider": "openai", "type": "ll", "enabled": True, "api_base": "http://a"},
        ]
        state = make_model_state(model_configs=configs)

        cols = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        mock_st.columns.side_effect = lambda widths, **kw: cols
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
        ):
            render_model_rows("ll")

        _, kwargs = cols[3].button.call_args
        assert kwargs["kwargs"]["model_type"] == "ll"
        assert kwargs["kwargs"]["action"] == "edit"
        assert kwargs["kwargs"]["model_id"] == "gpt-4o"
        assert kwargs["kwargs"]["model_provider"] == "openai"

    def test_add_button_triggers_edit_model(self, make_model_state, mock_st):
        """Add button calls edit_model with action='add'."""
        from client.app.content.config.tabs.models import render_model_rows

        state = make_model_state(model_configs=[])
        mock_st.columns.side_effect = lambda widths, **kw: [MagicMock() for _ in widths]
        mock_st.button.return_value = True

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
            patch(f"{MODULE}.edit_model") as mock_edit,
        ):
            render_model_rows("ll")

        mock_edit.assert_called_once_with(model_type="ll", action="add")


# ---------------------------------------------------------------------------
# edit_model
# ---------------------------------------------------------------------------


class TestEditModel:
    """Test edit_model dialog orchestration."""

    def test_successful_submission_triggers_rerun(self, make_model_state, mock_st):
        from client.app.content.config.tabs.models import edit_model

        state = make_model_state()
        mock_st.selectbox.return_value = "openai"
        mock_st.button.return_value = False
        mock_st.rerun.side_effect = Rerun

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._initialize_model", return_value={"id": "gpt-4o", "provider": "openai"}),
            patch(f"{MODULE}._get_supported_models", return_value=[{"provider": "openai", "ids": []}]),
            patch(
                f"{MODULE}._render_provider_selection",
                return_value=({"id": "gpt-4o", "provider": "openai"}, [], False),
            ),
            patch(f"{MODULE}._render_model_selection", side_effect=lambda model, *_: model),
            patch(f"{MODULE}._render_api_configuration", side_effect=lambda model, *_: model),
            patch(f"{MODULE}._render_model_specific_config", side_effect=lambda model, *_: model),
            patch(f"{MODULE}._handle_dialog_submission", return_value=True),
            pytest.raises(Rerun),
        ):
            getattr(edit_model, "__wrapped__")("ll", "add")

    def test_no_rerun_when_submission_false(self, make_model_state, mock_st):
        from client.app.content.config.tabs.models import edit_model

        state = make_model_state()
        mock_st.selectbox.return_value = "openai"
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._initialize_model", return_value={"id": "gpt-4o", "provider": "openai"}),
            patch(f"{MODULE}._get_supported_models", return_value=[{"provider": "openai", "ids": []}]),
            patch(
                f"{MODULE}._render_provider_selection",
                return_value=({"id": "gpt-4o", "provider": "openai"}, [], False),
            ),
            patch(f"{MODULE}._render_model_selection", side_effect=lambda model, *_: model),
            patch(f"{MODULE}._render_api_configuration", side_effect=lambda model, *_: model),
            patch(f"{MODULE}._render_model_specific_config", side_effect=lambda model, *_: model),
            patch(f"{MODULE}._handle_dialog_submission", return_value=False),
        ):
            getattr(edit_model, "__wrapped__")("embed", "edit", "gpt-4o", "openai")

        mock_st.rerun.assert_not_called()


# ---------------------------------------------------------------------------
# display_models
# ---------------------------------------------------------------------------


class TestDisplayModels:
    """Test display_models main entry point."""

    def test_renders_language_and_embedding_subheaders(self, mock_st):
        """Language and Embedding subheaders are rendered."""
        from client.app.content.config.tabs.models import display_models

        mock_st.container.return_value.__enter__ = MagicMock()
        mock_st.container.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.render_model_rows"),
        ):
            display_models()

        subheader_args = [c.args[0] for c in mock_st.subheader.call_args_list]
        assert "Language" in subheader_args
        assert "Embedding" in subheader_args

    def test_calls_render_model_rows_for_both_types(self, mock_st):
        """render_model_rows is called for both 'll' and 'embed'."""
        from client.app.content.config.tabs.models import display_models

        mock_st.container.return_value.__enter__ = MagicMock()
        mock_st.container.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.render_model_rows") as mock_rows,
        ):
            display_models()

        calls = [c.args[0] for c in mock_rows.call_args_list]
        assert "ll" in calls
        assert "embed" in calls
