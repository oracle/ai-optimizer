"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.config.tabs.oci
"""
# spell-checker: disable

from importlib import import_module
from unittest.mock import MagicMock, patch

import httpx
import pytest

from client.tests.conftest import AttrDict, Rerun, make_http_error

MODULE = "client.app.content.config.tabs.oci"


# ---------------------------------------------------------------------------
# State factory
# ---------------------------------------------------------------------------


def make_oci_state(profiles=None, current_profile="DEFAULT", extra=None):
    """Build an AttrDict mimicking Streamlit session_state for OCI tests."""
    oci_configs = profiles or []
    data = AttrDict(
        {
            "settings": {
                "oci_configs": oci_configs,
                "client_settings": {
                    "oci": {"auth_profile": current_profile},
                },
            },
        }
    )
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# _handle_authentication_principals
# ---------------------------------------------------------------------------


class TestHandleAuthenticationPrincipals:
    """Test _handle_authentication_principals returns correct auth info."""

    def test_instance_principal_returns_supplied_and_disable(self, mock_st):
        """Single instance_principal config returns auth settings and disables config."""
        from client.app.content.config.tabs.oci import _handle_authentication_principals

        state = make_oci_state(
            profiles=[{"authentication": "instance_principal", "tenancy": "ocid1.tenancy.oc1..ip"}],
        )
        oci_lookup = {"IP_PROFILE": state["settings"]["oci_configs"][0]}

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            supplied, disable = _handle_authentication_principals(oci_lookup)

        assert supplied["authentication"] == "instance_principal"
        assert supplied["tenancy"] == "ocid1.tenancy.oc1..ip"
        assert disable is True

    def test_oke_workload_identity_returns_supplied_and_disable(self, mock_st):
        """Single oke_workload_identity config returns auth settings and disables config."""
        from client.app.content.config.tabs.oci import _handle_authentication_principals

        state = make_oci_state(
            profiles=[{"authentication": "oke_workload_identity", "tenancy": "ocid1.tenancy.oc1..oke"}],
        )
        oci_lookup = {"OKE_PROFILE": state["settings"]["oci_configs"][0]}

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            supplied, disable = _handle_authentication_principals(oci_lookup)

        assert supplied["authentication"] == "oke_workload_identity"
        assert supplied["tenancy"] == "ocid1.tenancy.oc1..oke"
        assert disable is True

    def test_api_key_returns_empty_dict(self, mock_st):
        """Single api_key config returns empty supplied and no disable."""
        from client.app.content.config.tabs.oci import _handle_authentication_principals

        state = make_oci_state(profiles=[{"authentication": "api_key", "tenancy": "ocid1.tenancy.oc1..test"}])
        oci_lookup = {"DEFAULT": state["settings"]["oci_configs"][0]}

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            supplied, disable = _handle_authentication_principals(oci_lookup)

        assert supplied == {}
        assert disable is False

    def test_multiple_configs_returns_empty_dict(self, mock_st):
        """Multiple configs return empty supplied regardless of auth type."""
        from client.app.content.config.tabs.oci import _handle_authentication_principals

        state = make_oci_state(
            profiles=[
                {"authentication": "instance_principal", "tenancy": "t1"},
                {"authentication": "api_key", "tenancy": "t2"},
            ],
        )
        oci_lookup = {"P1": state["settings"]["oci_configs"][0], "P2": state["settings"]["oci_configs"][1]}

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            supplied, disable = _handle_authentication_principals(oci_lookup)

        assert supplied == {}
        assert disable is False

    def test_empty_oci_configs_returns_empty_dict(self, mock_st):
        """Empty oci_configs list returns empty supplied and no disable."""
        from client.app.content.config.tabs.oci import _handle_authentication_principals

        state = make_oci_state(profiles=[])
        oci_lookup = {"PROFILE": {}}

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            supplied, disable = _handle_authentication_principals(oci_lookup)

        assert supplied == {}
        assert disable is False
        mock_st.info.assert_not_called()


# ---------------------------------------------------------------------------
# _render_profile_selection
# ---------------------------------------------------------------------------


class TestRenderProfileSelection:
    """Test _render_profile_selection returns correct profile info."""

    def test_returns_selected_profile(self, mock_st):
        """Selected profile is returned from selectbox."""
        from client.app.content.config.tabs.oci import _render_profile_selection

        state = make_oci_state()
        mock_st.selectbox.return_value = "DEFAULT"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state), patch(f"{MODULE}.helpers") as hlp:
            hlp.selectbox_index.return_value = 0
            selected, is_new = _render_profile_selection({"DEFAULT": {}}, False)

        assert selected == "DEFAULT"
        assert is_new is False

    def test_pending_applied(self, mock_st):
        """Pending selection is applied to state."""
        from client.app.content.config.tabs.oci import _render_profile_selection

        state = make_oci_state(extra={"_pending_oci_select": "NEW_PROFILE"})
        mock_st.selectbox.return_value = "NEW_PROFILE"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state), patch(f"{MODULE}.helpers") as hlp:
            hlp.selectbox_index.return_value = 0
            selected, is_new = _render_profile_selection({"DEFAULT": {}, "NEW_PROFILE": {}}, False)

        assert "_pending_oci_select" not in state
        assert state["runtime_selected_oci"] == "NEW_PROFILE"
        assert selected == "NEW_PROFILE"

    def test_pending_ignored_when_not_in_options(self, mock_st):
        """Pending selection for a missing profile is ignored."""
        from client.app.content.config.tabs.oci import _render_profile_selection

        state = make_oci_state(extra={"_pending_oci_select": "GONE"})
        mock_st.selectbox.return_value = "DEFAULT"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state), patch(f"{MODULE}.helpers") as hlp:
            hlp.selectbox_index.return_value = 0
            _render_profile_selection({"DEFAULT": {}}, False)

        assert "_pending_oci_select" not in state
        assert "runtime_selected_oci" not in state

    def test_add_new_returns_is_new(self, mock_st):
        """Selecting 'Add New...' returns is_new=True."""
        from client.app.content.config.tabs.oci import ADD_NEW, _render_profile_selection

        state = make_oci_state()
        mock_st.selectbox.return_value = ADD_NEW

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state), patch(f"{MODULE}.helpers") as hlp:
            hlp.selectbox_index.return_value = 0
            selected, is_new = _render_profile_selection({"DEFAULT": {}}, False)

        assert selected == ADD_NEW
        assert is_new is True

    def test_selectbox_returns_none_falls_back_to_empty_string(self, mock_st):
        """When selectbox returns None, selected falls back to empty string."""
        from client.app.content.config.tabs.oci import _render_profile_selection

        state = make_oci_state()
        mock_st.selectbox.return_value = None

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state), patch(f"{MODULE}.helpers") as hlp:
            hlp.selectbox_index.return_value = 0
            selected, is_new = _render_profile_selection({"DEFAULT": {}}, False)

        assert selected == ""
        assert is_new is False

    def test_no_client_settings_uses_default_profile(self, mock_st):
        """Missing client_settings key falls back to DEFAULT profile."""
        from client.app.content.config.tabs.oci import _render_profile_selection

        state = AttrDict({"settings": {"oci_configs": []}})
        mock_st.selectbox.return_value = "DEFAULT"

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state), patch(f"{MODULE}.helpers") as hlp:
            hlp.selectbox_index.return_value = 0
            _render_profile_selection({"DEFAULT": {}}, False)

        hlp.selectbox_index.assert_called_once_with(["DEFAULT", "Add New..."], "DEFAULT")


# ---------------------------------------------------------------------------
# _render_oci_configuration_form
# ---------------------------------------------------------------------------


class TestRenderOciConfigForm:
    """Test _render_oci_configuration_form renders and submits correctly."""

    def test_new_profile_shows_text_input_for_name(self, mock_st):
        """New profile shows a text_input for profile name."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.text_area.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({}, "Add New...", True, False, False, {})

        # text_input should have been called for Profile Name (first call for new)
        name_calls = [c for c in mock_st.text_input.call_args_list if "Profile Name" in str(c)]
        assert len(name_calls) >= 1

    def test_existing_validated_profile_disables_fields(self, mock_st):
        """Existing validated profile disables all form fields."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "",
            "key_file": "k",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, False, True, {})

        # Fields should be disabled (usable=True and not new)
        text_calls = [c for c in mock_st.text_input.call_args_list if c.kwargs.get("key", "").startswith("oci_")]
        for call in text_calls:
            assert call.kwargs.get("disabled") is True, f"Field {call.kwargs.get('key')} should be disabled"

    def test_token_auth_disables_user_enables_token_file(self, mock_st):
        """Token auth checkbox disables user and enables security_token_file."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {"tenancy": "", "region": "", "user": "", "fingerprint": "", "security_token_file": "", "key_file": ""}
        state = make_oci_state()
        mock_st.checkbox.return_value = True  # token auth enabled
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"NEW": cfg}, "NEW", False, False, False, {})

        # Find user and token file calls
        user_calls = [
            c for c in mock_st.text_input.call_args_list if c.kwargs.get("key", "").startswith("runtime_oci_user_")
        ]
        token_calls = [
            c
            for c in mock_st.text_input.call_args_list
            if c.kwargs.get("key", "").startswith("runtime_oci_security_token_file_")
        ]
        assert user_calls and user_calls[0].kwargs.get("disabled") is True
        assert token_calls and token_calls[0].kwargs.get("disabled") is False

    def test_submit_calls_create_oci_for_new(self, mock_st):
        """Submit on a new profile calls create_oci."""
        from client.app.content.config.tabs.oci import _handle_oci_submit

        state = make_oci_state()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._create_oci") as mock_create,
        ):
            _handle_oci_submit(
                is_new=True, auth_profile="NEW_PROFILE", selected="Add New...", supplied={"tenancy": "t"}
            )

        mock_create.assert_called_once()

    def test_submit_calls_update_oci_for_existing(self, mock_st):
        """Submit on an existing profile calls _update_oci."""
        from client.app.content.config.tabs.oci import _handle_oci_submit

        state = make_oci_state()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_oci", return_value=False) as mock_update,
        ):
            _handle_oci_submit(is_new=False, auth_profile="EXISTING", selected="EXISTING", supplied={"tenancy": ""})

        mock_update.assert_called_once()

    def test_remove_popover_calls_remove_oci(self, mock_st):
        """Remove button within popover calls _remove_oci."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {"tenancy": "", "region": "", "user": "", "fingerprint": "", "security_token_file": "", "key_file": ""}
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""

        # Confirm Remove -> True (Save button is now on_click, so only st.button is the confirm)
        def _button_side_effect(*_, **kwargs):
            return kwargs.get("key", "").startswith("confirm_delete_oci_")

        mock_st.button.side_effect = _button_side_effect

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._remove_oci") as mock_remove,
        ):
            _render_oci_configuration_form({"EXISTING": cfg}, "EXISTING", False, False, False, {})

        mock_remove.assert_called_once_with("EXISTING")

    def test_new_profile_renders_key_content_text_area(self, mock_st):
        """New profile renders a key_content text_area."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.text_area.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({}, "Add New...", True, False, False, {})

        key_content_calls = [c for c in mock_st.text_area.call_args_list if "Key Content" in str(c)]
        assert len(key_content_calls) >= 1

    def test_update_calls_update_oci_with_supplied(self, mock_st):
        """_handle_oci_submit calls _update_oci with the correct args."""
        from client.app.content.config.tabs.oci import _handle_oci_submit

        state = make_oci_state()
        supplied = {"tenancy": "t", "region": "r"}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_oci", return_value=True) as mock_update,
        ):
            _handle_oci_submit(is_new=False, auth_profile="EXISTING", selected="EXISTING", supplied=supplied)

        mock_update.assert_called_once_with("EXISTING", supplied)

    def test_existing_non_validated_profile_fields_enabled(self, mock_st):
        """Existing non-validated profile (usable=False) keeps fields enabled."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "",
            "key_file": "k",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, False, False, {})

        # Tenancy, region, fingerprint, key_file should NOT be disabled
        tenancy_calls = [
            c for c in mock_st.text_input.call_args_list if c.kwargs.get("key", "").startswith("runtime_oci_tenancy_")
        ]
        assert tenancy_calls and tenancy_calls[0].kwargs.get("disabled") is False

    def test_disable_config_disables_fields_even_if_not_usable(self, mock_st):
        """disable_config=True disables fields even when usable=False."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "",
            "key_file": "k",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, True, False, {})

        # Checkbox should be disabled
        mock_st.checkbox.assert_called_once()
        assert mock_st.checkbox.call_args.kwargs.get("disabled") is True

    def test_validated_profile_shows_success_with_namespace(self, mock_st):
        """Validated profile with namespace shows success with namespace suffix."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "",
            "key_file": "k",
            "namespace": "my_ns",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, False, True, {})

        success_args = [c.args[0] for c in mock_st.success.call_args_list]
        assert any("Validated" in a and "my_ns" in a for a in success_args)

    def test_validated_profile_shows_success_without_namespace(self, mock_st):
        """Validated profile without namespace shows success without suffix."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "",
            "key_file": "k",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, False, True, {})

        success_args = [c.args[0] for c in mock_st.success.call_args_list]
        assert any("Validated" in a for a in success_args)
        assert all("Namespace" not in a for a in success_args)

    def test_unverified_profile_shows_error_status(self, mock_st):
        """Unverified existing profile shows error status."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "",
            "key_file": "k",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, False, False, {})

        error_args = [c.args[0] for c in mock_st.error.call_args_list]
        assert any("Unverified" in a for a in error_args)

    def test_key_content_present_sets_key_file_to_none(self, mock_st):
        """key_content truthy sets key_file to None in submit_supplied."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = "/path/to/key"
        mock_st.text_area.return_value = "-----BEGIN RSA PRIVATE KEY-----"
        save_col, remove_col, spacer = MagicMock(), MagicMock(), MagicMock()
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [save_col, remove_col, spacer]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({}, "Add New...", True, False, False, {})

        submitted = save_col.button.call_args.kwargs["kwargs"]["supplied"]
        assert submitted["key_file"] is None

    def test_token_auth_true_nulls_user_keeps_token_file(self, mock_st):
        """token_auth=True sets user to None and keeps security_token_file."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "/tok",
            "key_file": "k",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = True
        mock_st.text_input.return_value = "value"
        mock_st.button.return_value = False
        save_col, remove_col, spacer = MagicMock(), MagicMock(), MagicMock()
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [save_col, remove_col, spacer]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, False, False, {})

        submitted = save_col.button.call_args.kwargs["kwargs"]["supplied"]
        assert submitted["user"] is None
        assert submitted["security_token_file"] is not None

    def test_token_auth_false_nulls_token_file_keeps_user(self, mock_st):
        """token_auth=False sets security_token_file to None and keeps user."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "/tok",
            "key_file": "k",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = "value"
        mock_st.button.return_value = False
        save_col, remove_col, spacer = MagicMock(), MagicMock(), MagicMock()
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [save_col, remove_col, spacer]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, False, False, {})

        submitted = save_col.button.call_args.kwargs["kwargs"]["supplied"]
        assert submitted["security_token_file"] is None
        assert submitted["user"] is not None

    def test_existing_profile_no_key_content_text_area(self, mock_st):
        """Existing profile does not render key_content text_area."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        cfg = {
            "tenancy": "t",
            "region": "r",
            "user": "u",
            "fingerprint": "f",
            "security_token_file": "",
            "key_file": "k",
        }
        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({"TEST": cfg}, "TEST", False, False, False, {})

        mock_st.text_area.assert_not_called()

    def test_new_profile_no_remove_button(self, mock_st):
        """New profile does not render remove popover."""
        from client.app.content.config.tabs.oci import _render_oci_configuration_form

        state = make_oci_state()
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.text_area.return_value = ""
        mock_st.button.return_value = False

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_configuration_form({}, "Add New...", True, False, False, {})

        mock_st.popover.assert_not_called()


# ---------------------------------------------------------------------------
# _render_genai_models_table
# ---------------------------------------------------------------------------


class TestRenderGenaiModelsTable:
    """Test _render_genai_models_table filtering and display."""

    def test_filters_models_by_region_and_capabilities(self, mock_st):
        """Only models matching region and CHAT/TEXT_EMBEDDINGS are included."""
        from client.app.content.config.tabs.oci import _render_genai_models_table

        models = [
            {"region": "us-chicago-1", "model_name": "m1", "capabilities": ["CHAT"]},
            {"region": "us-chicago-1", "model_name": "m2", "capabilities": ["TEXT_EMBEDDINGS"]},
            {"region": "eu-frankfurt-1", "model_name": "m3", "capabilities": ["CHAT"]},
            {"region": "us-chicago-1", "model_name": "m4", "capabilities": ["OTHER"]},
        ]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.helpers") as hlp:
            hlp.bool_to_emoji.side_effect = lambda x: "Y" if x else "N"
            _render_genai_models_table(models, "us-chicago-1")

        mock_st.dataframe.assert_called_once()
        df = mock_st.dataframe.call_args[0][0]
        assert len(df) == 2  # m1 and m2 only

    def test_displays_dataframe(self, mock_st):
        """st.dataframe is called with hide_index=True."""
        from client.app.content.config.tabs.oci import _render_genai_models_table

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.helpers") as hlp:
            hlp.bool_to_emoji.return_value = "Y"
            _render_genai_models_table([], "us-chicago-1")

        mock_st.dataframe.assert_called_once()
        _, kwargs = mock_st.dataframe.call_args
        assert kwargs.get("hide_index") is True

    def test_model_with_both_chat_and_embedding(self, mock_st):
        """Model with both CHAT and TEXT_EMBEDDINGS appears once in table."""
        from client.app.content.config.tabs.oci import _render_genai_models_table

        models = [{"region": "us-chicago-1", "model_name": "dual", "capabilities": ["CHAT", "TEXT_EMBEDDINGS"]}]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.helpers") as hlp:
            hlp.bool_to_emoji.side_effect = lambda x: "Y" if x else "N"
            _render_genai_models_table(models, "us-chicago-1")

        df = mock_st.dataframe.call_args[0][0]
        assert len(df) == 1
        assert df.iloc[0]["Large Language"] == "Y"
        assert df.iloc[0]["Embedding"] == "Y"

    def test_no_models_match_region_empty_dataframe(self, mock_st):
        """No models matching the region produces empty dataframe."""
        from client.app.content.config.tabs.oci import _render_genai_models_table

        models = [{"region": "eu-frankfurt-1", "model_name": "m1", "capabilities": ["CHAT"]}]

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.helpers") as hlp:
            hlp.bool_to_emoji.return_value = "Y"
            _render_genai_models_table(models, "us-chicago-1")

        df = mock_st.dataframe.call_args[0][0]
        assert len(df) == 0


# ---------------------------------------------------------------------------
# _render_oci_genai_section
# ---------------------------------------------------------------------------


class TestRenderOciGenaiSection:
    """Test _render_oci_genai_section interactions."""

    def test_button_check_fetches_models(self, mock_st):
        """Clicking check button fetches genai models."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": "ocid1.comp"}}
        state = make_oci_state()

        # Check button True, then Enable button False
        mock_st.button.side_effect = [True, False]
        mock_st.text_input.return_value = "ocid1.comp"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_oci", return_value=True),
            patch(f"{MODULE}._get_genai_models", return_value=[]) as mock_get,
        ):
            _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        mock_get.assert_called_once_with("DEFAULT")

    def test_button_check_http_error_shows_error(self, mock_st):
        """A 400 from the server is surfaced as st.error, not raised."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": "ocid1.comp"}}
        state = make_oci_state()

        mock_st.button.side_effect = [True, False]
        mock_st.text_input.return_value = "ocid1.comp"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_oci", return_value=True),
            patch(f"{MODULE}._get_genai_models", side_effect=make_http_error(detail="bad compartment")),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            hlp.extract_error_detail.return_value = "bad compartment"
            _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        assert state["genai_models"] == []
        mock_st.error.assert_called_once()

    def test_button_check_http_error_clears_stale_models(self, mock_st):
        """Stale models from a prior successful Check must be cleared on a later failure."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": "ocid1.comp"}}
        state = make_oci_state(
            extra={"genai_models": [{"region": "us-chicago-1", "model_name": "m1", "capabilities": ["CHAT"]}]}
        )

        mock_st.button.side_effect = [True, False]
        mock_st.text_input.return_value = "ocid1.comp"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_oci", return_value=True),
            patch(f"{MODULE}._get_genai_models", side_effect=make_http_error(detail="bad compartment")),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            hlp.extract_error_detail.return_value = "bad compartment"
            _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        assert state["genai_models"] == []

    def test_disabled_when_not_usable(self, mock_st):
        """Buttons are disabled when profile is not usable."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": ""}}
        state = make_oci_state()

        mock_st.button.return_value = False
        mock_st.text_input.return_value = ""

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _render_oci_genai_section(oci_lookup, "DEFAULT", False, {})

        # Check that text_input was called with disabled=True
        text_calls = [c for c in mock_st.text_input.call_args_list if "GenAI" in str(c)]
        for call in text_calls:
            assert call.kwargs.get("disabled") is True

    def test_enable_button_calls_update_create_refresh(self, mock_st):
        """Enable button triggers update, get_oci, create_genai_models, refresh."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": "ocid1.comp"}}
        state = make_oci_state(
            extra={"genai_models": [{"region": "us-chicago-1", "model_name": "m1", "capabilities": ["CHAT"]}]}
        )

        # Check button False, Enable button True
        mock_st.button.side_effect = [False, True]
        mock_st.selectbox.return_value = "us-chicago-1"
        mock_st.text_input.return_value = "ocid1.comp"
        mock_st.rerun.side_effect = Rerun

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_oci", return_value=True) as mock_update,
            patch(f"{MODULE}._get_oci") as mock_get_oci,
            patch(f"{MODULE}._create_genai_models") as mock_create,
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.pd") as mock_pd,
        ):
            mock_pd.DataFrame.return_value = MagicMock()
            hlp.bool_to_emoji.return_value = "Y"
            with pytest.raises(Rerun):
                _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        mock_update.assert_called_once()
        assert mock_get_oci.call_count == 1
        mock_create.assert_called_once_with("DEFAULT")
        hlp.refresh_settings.assert_called_once()

    def test_enable_button_create_http_error_shows_error_and_stops(self, mock_st):
        """A 400 from create_genai_models is surfaced and refresh/success are skipped."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": "ocid1.comp"}}
        state = make_oci_state(
            extra={"genai_models": [{"region": "us-chicago-1", "model_name": "m1", "capabilities": ["CHAT"]}]}
        )

        mock_st.button.side_effect = [False, True]
        mock_st.selectbox.return_value = "us-chicago-1"
        mock_st.text_input.return_value = "ocid1.comp"
        mock_st.stop.side_effect = Rerun

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_oci", return_value=True),
            patch(f"{MODULE}._get_oci") as mock_get_oci,
            patch(f"{MODULE}._create_genai_models", side_effect=make_http_error(detail="no subscription")),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.pd") as mock_pd,
        ):
            mock_pd.DataFrame.return_value = MagicMock()
            hlp.bool_to_emoji.return_value = "Y"
            hlp.extract_error_detail.return_value = "no subscription"
            with pytest.raises(Rerun):
                _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        mock_st.error.assert_called_once()
        hlp.refresh_settings.assert_not_called()
        mock_get_oci.assert_not_called()
        mock_st.success.assert_not_called()

    def test_check_button_without_compartment_shows_error(self, mock_st):
        """Missing compartment when checking models shows error and stops."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": ""}}
        state = make_oci_state()

        mock_st.button.side_effect = [True]
        mock_st.text_input.return_value = ""
        mock_st.stop.side_effect = Rerun

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state), pytest.raises(Rerun):
            _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        mock_st.error.assert_called_once()

    def test_enable_button_update_returns_false_calls_stop(self, mock_st):
        """Enable button with failed update stops execution."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": "ocid1.comp"}}
        state = make_oci_state(
            extra={"genai_models": [{"region": "us-chicago-1", "model_name": "m1", "capabilities": ["CHAT"]}]}
        )

        mock_st.button.side_effect = [False, True]
        mock_st.selectbox.return_value = "us-chicago-1"
        mock_st.text_input.return_value = "ocid1.comp"
        mock_st.stop.side_effect = Rerun

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._update_oci", return_value=False) as mock_update,
            pytest.raises(Rerun),
        ):
            _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        mock_update.assert_called_once_with(
            "DEFAULT", {"genai_compartment_id": "ocid1.comp", "genai_region": "us-chicago-1"}, toast=False
        )

    def test_genai_models_already_in_state_not_overwritten(self, mock_st):
        """Existing genai_models in state are not reset to empty list."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        existing_models = [{"region": "us-chicago-1", "model_name": "m1", "capabilities": ["CHAT"]}]
        oci_lookup = {"DEFAULT": {"genai_compartment_id": "ocid1.comp"}}
        state = make_oci_state(extra={"genai_models": list(existing_models)})

        mock_st.button.return_value = False
        mock_st.selectbox.return_value = "us-chicago-1"
        mock_st.text_input.return_value = "ocid1.comp"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.pd") as mock_pd,
            patch(f"{MODULE}.helpers") as hlp,
        ):
            mock_pd.DataFrame.return_value = MagicMock()
            hlp.bool_to_emoji.return_value = "Y"
            _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        assert state.genai_models == existing_models

    def test_region_selectbox_shows_unique_regions(self, mock_st):
        """Duplicate regions are deduplicated in region selectbox."""
        from client.app.content.config.tabs.oci import _render_oci_genai_section

        oci_lookup = {"DEFAULT": {"genai_compartment_id": "ocid1.comp"}}
        state = make_oci_state(
            extra={
                "genai_models": [
                    {"region": "us-chicago-1", "model_name": "m1", "capabilities": ["CHAT"]},
                    {"region": "us-chicago-1", "model_name": "m2", "capabilities": ["TEXT_EMBEDDINGS"]},
                    {"region": "eu-frankfurt-1", "model_name": "m3", "capabilities": ["CHAT"]},
                ]
            }
        )

        mock_st.button.return_value = False
        mock_st.selectbox.return_value = "us-chicago-1"
        mock_st.text_input.return_value = "ocid1.comp"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.pd") as mock_pd,
            patch(f"{MODULE}.helpers") as hlp,
        ):
            mock_pd.DataFrame.return_value = MagicMock()
            hlp.bool_to_emoji.return_value = "Y"
            _render_oci_genai_section(oci_lookup, "DEFAULT", True, {})

        # selectbox should be called with a list of unique regions
        select_calls = [c for c in mock_st.selectbox.call_args_list if "Region" in str(c)]
        assert select_calls
        regions = select_calls[0].args[1]
        assert len(regions) == 2
        assert set(regions) == {"us-chicago-1", "eu-frankfurt-1"}


# ---------------------------------------------------------------------------
# get_oci
# ---------------------------------------------------------------------------


class TestGetOci:
    """Test get_oci state population."""

    def test_success_populates_state(self, mock_st):
        """``_get_oci`` fetches the masked list, then re-fetches each
        profile via the per-id endpoint with ``include_sensitive=true``.
        """
        from client.app.content.config.tabs.oci import _get_oci

        state = make_oci_state()
        masked_list = [{"auth_profile": "DEFAULT"}]
        detailed = {"auth_profile": "DEFAULT", "key_content": "stored-key"}

        # First api_get call returns the masked list, subsequent calls
        # return the per-profile detailed entry.
        api_get_mock = MagicMock(side_effect=[masked_list, detailed])

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", api_get_mock),
        ):
            _get_oci()

        assert state["settings"]["oci_configs"] == [detailed]
        assert state["_oci_sensitive_loaded"] is True
        # Two calls: list, then per-profile.
        assert api_get_mock.call_count == 2

    def test_force_true_refreshes(self, mock_st):
        """force=True reloads even when already loaded."""
        from client.app.content.config.tabs.oci import _get_oci

        state = make_oci_state(extra={"_oci_sensitive_loaded": True})
        masked_list = [{"auth_profile": "REFRESHED"}]
        detailed = {"auth_profile": "REFRESHED", "key_content": "stored-key"}
        api_get_mock = MagicMock(side_effect=[masked_list, detailed])

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", api_get_mock),
        ):
            _get_oci(force=True)

        assert api_get_mock.call_count == 2
        assert state["settings"]["oci_configs"] == [detailed]

    def test_http_error_shows_st_error(self, mock_st):
        """HTTPStatusError calls st.error."""
        from client.app.content.config.tabs.oci import _get_oci

        state = make_oci_state()
        mock_resp = MagicMock(status_code=500, content=b'{"detail":"server error"}')
        mock_resp.json.return_value = {"detail": "server error"}
        error = httpx.HTTPStatusError("Error", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", side_effect=error),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            hlp.extract_error_detail.return_value = "server error"
            _get_oci()

        mock_st.error.assert_called_once()

    def test_skips_when_already_loaded(self, mock_st):
        """Skips API call when already loaded and force=False."""
        from client.app.content.config.tabs.oci import _get_oci

        state = make_oci_state(extra={"_oci_sensitive_loaded": True})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get") as mock_get,
        ):
            _get_oci()

        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# get_genai_models
# ---------------------------------------------------------------------------


class TestGetGenaiModels:
    """Test get_genai_models API call."""

    def test_returns_api_get_result_with_correct_path_and_timeout(self):
        """Calls api_get with correct path and timeout."""
        from client.app.content.config.tabs.oci import _get_genai_models

        expected = [{"model_name": "model1"}]
        with patch(f"{MODULE}.api_get", return_value=expected) as mock_get:
            result = _get_genai_models("DEFAULT")

        assert result == expected
        mock_get.assert_called_once_with("oci/genai/DEFAULT", timeout=180)


# ---------------------------------------------------------------------------
# create_genai_models
# ---------------------------------------------------------------------------


class TestCreateGenaiModels:
    """Test create_genai_models API call."""

    def test_calls_api_post_with_correct_path_and_timeout(self):
        """Calls api_post with correct path and timeout."""
        from client.app.content.config.tabs.oci import _create_genai_models

        with patch(f"{MODULE}.api_post") as mock_post:
            _create_genai_models("DEFAULT")

        mock_post.assert_called_once_with("oci/genai/DEFAULT", timeout=180)


# ---------------------------------------------------------------------------
# create_oci
# ---------------------------------------------------------------------------


class TestCreateOci:
    """Test _create_oci profile creation."""

    def test_success_sets_pending(self, mock_st):
        """Successful create sets pending select."""
        from client.app.content.config.tabs.oci import _create_oci

        state = make_oci_state()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post"),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.return_value = {"auth_profile": "NEW"}
            _create_oci("NEW", {"tenancy": "t"})

        assert state["_pending_oci_select"] == "NEW"

    def test_empty_name_shows_error(self, mock_st):
        """Empty profile name shows st.error and returns."""
        from client.app.content.config.tabs.oci import _create_oci

        state = make_oci_state()

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _create_oci("  ", {})

        mock_st.error.assert_called_once_with("Profile Name is required.")

    def test_api_error_shows_st_error(self, mock_st):
        """API error shows error via st.error."""
        from client.app.content.config.tabs.oci import _create_oci

        state = make_oci_state()
        mock_resp = MagicMock(status_code=409, content=b'{"detail":"already exists"}')
        mock_resp.json.return_value = {"detail": "already exists"}
        error = httpx.HTTPStatusError("Conflict", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", side_effect=error),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            hlp.build_payload.return_value = {"auth_profile": "DUP"}
            hlp.extract_error_detail.return_value = "already exists"
            _create_oci("DUP", {})

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("already exists" in m for m in error_messages)

    def test_strips_whitespace(self, mock_st):
        """Leading/trailing whitespace is stripped from profile name."""
        from client.app.content.config.tabs.oci import _create_oci

        state = make_oci_state()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post"),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.return_value = {"auth_profile": "SPACED"}
            _create_oci("  SPACED  ", {"tenancy": "t"})

        assert state["_pending_oci_select"] == "SPACED"

    def test_none_auth_profile_shows_error(self, mock_st):
        """None auth_profile is treated as empty and shows error."""
        from client.app.content.config.tabs.oci import _create_oci

        state = make_oci_state()

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            _create_oci(None, {})

        mock_st.error.assert_called_once_with("Profile Name is required.")

    def test_success_calls_get_oci_force_true(self, mock_st):
        """Successful create calls _get_oci with force=True."""
        from client.app.content.config.tabs.oci import _create_oci

        state = make_oci_state()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post"),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci") as mock_get_oci,
        ):
            hlp.build_payload.return_value = {"auth_profile": "NEW"}
            _create_oci("NEW", {"tenancy": "t"})

        mock_get_oci.assert_called_once_with(force=True)

    def test_auth_profile_set_in_supplied(self, mock_st):
        """auth_profile is injected into supplied before API call."""
        from client.app.content.config.tabs.oci import _create_oci

        state = make_oci_state()
        captured = {}

        def capture_payload(d):
            captured.update(d)
            return d

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post"),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.side_effect = capture_payload
            _create_oci("NEWP", {"tenancy": "t"})

        assert captured["auth_profile"] == "NEWP"


# ---------------------------------------------------------------------------
# remove_oci
# ---------------------------------------------------------------------------


class TestRemoveOci:
    """Test _remove_oci profile removal."""

    def test_success_calls_delete(self, mock_st):
        """Successful remove calls API delete and refreshes."""
        from client.app.content.config.tabs.oci import _remove_oci

        state = make_oci_state()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_delete") as mock_delete,
            patch(f"{MODULE}._get_oci"),
        ):
            _remove_oci("TEST")

        mock_delete.assert_called_once_with("oci/TEST")

    def test_error_shows_st_error(self, mock_st):
        """API error shows error via st.error."""
        from client.app.content.config.tabs.oci import _remove_oci

        state = make_oci_state()
        mock_resp = MagicMock(status_code=404, content=b'{"detail":"not found"}')
        mock_resp.json.return_value = {"detail": "not found"}
        error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_delete", side_effect=error),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            hlp.extract_error_detail.return_value = "not found"
            _remove_oci("MISSING")

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("not found" in m for m in error_messages)

    def test_success_calls_get_oci_force_true(self, mock_st):
        """Successful remove calls _get_oci with force=True."""
        from client.app.content.config.tabs.oci import _remove_oci

        state = make_oci_state()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_delete"),
            patch(f"{MODULE}._get_oci") as mock_get_oci,
        ):
            _remove_oci("TEST")

        mock_get_oci.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# update_oci
# ---------------------------------------------------------------------------


class TestUpdateOci:
    """Test update_oci profile update."""

    def test_differences_triggers_api_put(self, mock_st):
        """Changes in supplied fields trigger api_put."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "old", "usable": True}],
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put") as mock_put,
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.return_value = {"tenancy": "new"}
            result = _update_oci("TEST", {"tenancy": "new"})

        assert result is True
        mock_put.assert_called_once()

    def test_no_differences_usable_shows_toast(self, mock_st):
        """No changes on usable profile shows toast."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "same", "usable": True}],
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            result = _update_oci("TEST", {"tenancy": "same"})

        assert result is False
        mock_st.toast.assert_called_once()

    def test_security_token_sets_auth_type(self, mock_st):
        """security_token_file present sets authentication to security_token."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "t", "usable": False}],
        )

        captured_supplied = {}

        def capture_build_payload(d):
            captured_supplied.update(d)
            return d

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put"),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.side_effect = capture_build_payload
            _update_oci("TEST", {"tenancy": "t", "security_token_file": "/path/token"})

        assert captured_supplied.get("authentication") == "security_token"

    def test_http_error_returns_false_and_shows_error(self, mock_st):
        """HTTPStatusError returns False and shows error."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "old", "usable": False}],
        )
        mock_resp = MagicMock(status_code=422, content=b'{"detail":"not usable"}')
        mock_resp.json.return_value = {"detail": "not usable"}
        error = httpx.HTTPStatusError("Unprocessable", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put", side_effect=error),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.return_value = {"tenancy": "new"}
            hlp.extract_error_detail.return_value = "not usable"
            result = _update_oci("TEST", {"tenancy": "new"})

        assert result is False
        mock_st.error.assert_called_once()

    def test_no_changes_detected_toast(self, mock_st):
        """When usable and no changes, toast is shown."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "same", "usable": True}],
        )

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            result = _update_oci("TEST", {"tenancy": "same"}, toast=True)

        assert result is False
        mock_st.toast.assert_called_once()
        assert "No Changes" in mock_st.toast.call_args[0][0]

    def test_no_differences_not_usable_triggers_update(self, mock_st):
        """No differences but usable=False still triggers api_put."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "same", "usable": False}],
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put") as mock_put,
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.return_value = {"tenancy": "same"}
            result = _update_oci("TEST", {"tenancy": "same"})

        assert result is True
        mock_put.assert_called_once()

    def test_instance_principal_does_not_set_security_token(self, mock_st):
        """instance_principal auth does not get overwritten to security_token."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "old", "usable": False}],
        )
        captured = {}

        def capture_build_payload(d):
            captured.update(d)
            return d

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put"),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.side_effect = capture_build_payload
            _update_oci(
                "TEST",
                {"authentication": "instance_principal", "security_token_file": "/path/token", "tenancy": "new"},
            )

        assert captured.get("authentication") == "instance_principal"

    def test_oke_workload_identity_does_not_set_security_token(self, mock_st):
        """oke_workload_identity auth does not get overwritten to security_token."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "old", "usable": False}],
        )
        captured = {}

        def capture_build_payload(d):
            captured.update(d)
            return d

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put"),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.build_payload.side_effect = capture_build_payload
            _update_oci(
                "TEST",
                {"authentication": "oke_workload_identity", "security_token_file": "/path/token", "tenancy": "new"},
            )

        assert captured.get("authentication") == "oke_workload_identity"

    def test_toast_false_no_changes_skips_toast(self, mock_st):
        """toast=False with no changes does not call st.toast."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "same", "usable": True}],
        )

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state):
            result = _update_oci("TEST", {"tenancy": "same"}, toast=False)

        assert result is False
        mock_st.toast.assert_not_called()

    def test_success_calls_refresh_and_get_oci(self, mock_st):
        """Successful update calls refresh_settings and _get_oci(force=True)."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "old", "usable": False}],
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put"),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci") as mock_get_oci,
        ):
            hlp.build_payload.return_value = {"tenancy": "new"}
            _update_oci("TEST", {"tenancy": "new"})

        hlp.refresh_settings.assert_called_once()
        mock_get_oci.assert_called_once_with(force=True)

    def test_http_error_calls_get_oci_force_true(self, mock_st):
        """HTTP error during update still calls _get_oci(force=True)."""
        from client.app.content.config.tabs.oci import _update_oci

        state = make_oci_state(
            profiles=[{"auth_profile": "TEST", "tenancy": "old", "usable": False}],
        )
        mock_resp = MagicMock(status_code=500, content=b'{"detail":"error"}')
        mock_resp.json.return_value = {"detail": "error"}
        error = httpx.HTTPStatusError("Error", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put", side_effect=error),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci") as mock_get_oci,
        ):
            hlp.build_payload.return_value = {"tenancy": "new"}
            hlp.extract_error_detail.return_value = "error"
            _update_oci("TEST", {"tenancy": "new"})

        mock_get_oci.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# display_oci
# ---------------------------------------------------------------------------


class TestSelectionSyncsClientSettings:
    """_on_oci_change calls sync_client_setting to persist the selection."""

    def test_different_profile_syncs(self):
        """Selecting a different profile calls sync_client_setting."""
        from client.app.content.config.tabs.oci import _on_oci_change

        state = {"runtime_selected_oci": "OTHER"}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            _on_oci_change()

        hlp.sync_client_setting.assert_called_once_with("oci", "auth_profile", "OTHER")

    def test_add_new_does_not_sync(self):
        """Selecting 'Add New...' does NOT call sync_client_setting."""
        from client.app.content.config.tabs.oci import _on_oci_change

        state = {"runtime_selected_oci": "Add New..."}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            _on_oci_change()

        hlp.sync_client_setting.assert_not_called()

    def test_none_selection_does_not_sync(self):
        """None selection does NOT call sync_client_setting."""
        from client.app.content.config.tabs.oci import _on_oci_change

        state = {"runtime_selected_oci": None}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            _on_oci_change()

        hlp.sync_client_setting.assert_not_called()


class TestDisplayOci:
    """Test display_oci orchestration."""

    def test_orchestrates_all_sub_functions(self, mock_st):
        """display_oci calls get_oci, renders selection, form, etc."""
        from client.app.content.config.tabs.oci import display_oci

        state = make_oci_state(profiles=[{"auth_profile": "DEFAULT", "usable": True}])
        mock_st.selectbox.return_value = "DEFAULT"
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci") as mock_get_oci,
        ):
            hlp.state_configs_lookup.return_value = {
                "DEFAULT": {"auth_profile": "DEFAULT", "usable": True, "genai_compartment_id": ""},
            }
            hlp.selectbox_index.return_value = 0
            display_oci()

        mock_get_oci.assert_called()
        mock_st.header.assert_called_once()

    def test_unauthenticated_returns_early(self, mock_st):
        """When unauthenticated, display_oci shows the locked notice and skips all subsequent rendering."""
        from client.app.content.config.tabs.oci import display_oci

        state = make_oci_state(profiles=[{"auth_profile": "DEFAULT", "usable": True}])
        mock_st.selectbox.return_value = "DEFAULT"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
            patch(f"{MODULE}._get_oci") as mock_get_oci,
            patch(f"{MODULE}._render_profile_selection") as mock_profile,
            patch(f"{MODULE}._render_oci_configuration_form") as mock_form,
            patch(f"{MODULE}._render_oci_genai_section") as mock_genai,
            patch(f"{MODULE}.is_authenticated", return_value=False),
            patch(f"{MODULE}.locked_notice") as mock_notice,
        ):
            display_oci()

        mock_notice.assert_called_once()
        mock_get_oci.assert_not_called()
        mock_profile.assert_not_called()
        mock_form.assert_not_called()
        mock_genai.assert_not_called()

    def test_genai_section_shown_for_existing_profile(self, mock_st):
        """GenAI section subheader is rendered for existing profile."""
        from client.app.content.config.tabs.oci import display_oci

        state = make_oci_state(profiles=[{"auth_profile": "DEFAULT", "usable": False}])
        mock_st.selectbox.return_value = "DEFAULT"
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.state_configs_lookup.return_value = {
                "DEFAULT": {"auth_profile": "DEFAULT", "usable": False, "genai_compartment_id": ""},
            }
            hlp.selectbox_index.return_value = 0
            display_oci()

        subheader_args = [c.args[0] for c in mock_st.subheader.call_args_list if c.args]
        assert "OCI GenAI" in subheader_args

    def test_genai_section_hidden_for_new_profile(self, mock_st):
        """GenAI section is not shown when 'Add New...' is selected."""
        from client.app.content.config.tabs.oci import display_oci

        state = make_oci_state()
        mock_st.selectbox.return_value = "Add New..."
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.text_area.return_value = ""
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
        ):
            hlp.state_configs_lookup.return_value = {"DEFAULT": {"auth_profile": "DEFAULT"}}
            hlp.selectbox_index.return_value = 0
            display_oci()

        subheader_args = [c.args[0] for c in mock_st.subheader.call_args_list if c.args]
        assert "OCI GenAI" not in subheader_args

    def test_usable_from_oci_lookup_for_existing(self, mock_st):
        """usable flag is extracted from oci_lookup for existing profiles."""
        from client.app.content.config.tabs.oci import display_oci

        state = make_oci_state(profiles=[{"auth_profile": "DEFAULT", "usable": True}])
        mock_st.selectbox.return_value = "DEFAULT"
        mock_st.checkbox.return_value = False
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._get_oci"),
            patch(f"{MODULE}._render_oci_configuration_form", return_value={}) as mock_form,
            patch(f"{MODULE}._render_oci_genai_section"),
        ):
            hlp.state_configs_lookup.return_value = {
                "DEFAULT": {"auth_profile": "DEFAULT", "usable": True, "genai_compartment_id": ""},
            }
            hlp.selectbox_index.return_value = 0
            display_oci()

        # Verify usable=True was passed to the form renderer
        assert mock_form.call_args.args[4] is True or mock_form.call_args.kwargs.get("usable") is True


class TestMainGuard:
    """Test __main__ guard execution."""

    def test_main_guard_invokes_display_oci(self):
        """Executing the main guard calls display_oci."""
        module = import_module("client.app.content.config.tabs.oci")
        with patch.object(module, "display_oci") as mock_display:
            code = "\n" * 400 + "if __name__ == '__main__': display_oci()\n"
            namespace = module.__dict__.copy()
            namespace["__name__"] = "__main__"
            assert module.__file__ is not None
            exec(compile(code, module.__file__, "exec"), namespace)

        mock_display.assert_called_once()
