"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore mult selectbox testset testsets subtools

import json
import logging
import math
import random
import string
from io import BytesIO
from typing import Optional

import httpx
import pandas as pd
import streamlit as st
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Wedge
from streamlit import session_state as state

from client.app.core import sidebar
from client.app.core.api import api_delete, api_get, api_post
from client.app.core.auth import is_authenticated, locked_notice
from client.app.core.helpers import (
    enabled_models_lookup,
    extract_error_detail,
    selectbox_index,
    state_configs_lookup,
    unique_file_payload,
    update_client_settings,
)

LOGGER = logging.getLogger("content.testbed")


#####################################################
# Local Helpers
#####################################################
def _is_db_configured() -> bool:
    """Check whether a usable database is configured."""
    db_alias = state["settings"]["client_settings"].get("database", {}).get("alias")
    if not db_alias:
        return False
    db_lookup = state_configs_lookup("database_configs", "alias")
    db_config = db_lookup.get(db_alias)
    return bool(db_config and db_config.get("usable"))


def _model_identity_to_key(mi: dict | None) -> str | None:
    """Convert a ModelIdentity dict to 'provider/id' string."""
    if mi and mi.get("provider") and mi.get("id"):
        return f"{mi['provider']}/{mi['id']}"
    return None


def _sync_testbed_model(field: str, widget_key: str) -> None:
    """Persist a testbed model selection to the server."""
    value = state.get(widget_key)
    if not value or "/" not in value:
        return
    provider, model_id = value.split("/", 1)
    update_client_settings({"testbed": {field: {"provider": provider, "id": model_id}}})


#####################################################
# State Management
#####################################################
def _reset_testset(cache: bool = False) -> None:
    """Clear all testbed state."""
    for key in (
        "runtime_testbed",
        "runtime_testbed_qa",
        "runtime_testbed_db_testsets",
        "runtime_testbed_evaluations",
    ):
        state.pop(key, None)
    if cache:
        _get_testbed_db_testsets.clear()


@st.cache_data(show_spinner="Retrieving TestSets")
def _get_testbed_db_testsets() -> list:
    """Get database testsets (cached)."""
    return api_get("testbed/testsets")


#####################################################
# Q&A CRUD
#####################################################
def _qa_delete() -> None:
    """Delete Q&A test set from database."""
    tid = state.runtime_testbed["testset_id"]
    try:
        api_delete(
            f"testbed/testset_delete/{tid}",
            toast=f"Test Set and Evaluations Deleted: {state.runtime_testbed['testset_name']}",
        )
        _reset_testset(True)
    except httpx.HTTPStatusError as exc:
        st.error(f"Failed to delete test set: {extract_error_detail(exc)}")


def _qa_update_db() -> None:
    """Save current Q&A to database."""
    _update_record(0)
    json_data = json.dumps(state.runtime_testbed_qa)
    qa_file = BytesIO(json_data.encode("utf-8"))
    files = [("files", ("data.json", qa_file, "application/json"))]
    data = {
        "name": state.runtime_new_testset_name,
        "tid": state.runtime_testbed["testset_id"],
    }
    api_post("testbed/testset_load", files=files, data=data, timeout=120)
    state.pop("runtime_testbed_db_testsets", None)
    _get_testbed_db_testsets.clear()
    state.runtime_testbed_db_testsets = _get_testbed_db_testsets()


@st.fragment()
def _update_record(direction: int = 0) -> None:
    """Save current record changes and navigate."""
    idx = state.runtime_testbed["qa_index"]
    state.runtime_testbed_qa[idx]["question"] = state[f"runtime_q_{idx}"]
    state.runtime_testbed_qa[idx]["reference_answer"] = state[f"runtime_a_{idx}"]
    state.runtime_testbed["qa_index"] += direction


@st.fragment()
def _delete_record() -> None:
    """Delete current Q&A record."""
    state.runtime_testbed_qa.pop(state.runtime_testbed["qa_index"])
    if len(state.runtime_testbed_qa) > 0:
        if state.runtime_testbed["qa_index"] >= len(state.runtime_testbed_qa):
            state.runtime_testbed["qa_index"] = len(state.runtime_testbed_qa) - 1
    else:
        state.runtime_testbed["qa_index"] = 0


#####################################################
# UI Components
#####################################################
def _qa_update_gui(qa_testset: list) -> None:
    """Render Q&A record editor."""
    dataframe = pd.DataFrame(qa_testset)
    records = dataframe.shape[0]
    idx = state.runtime_testbed["qa_index"]

    st.write(f"Record: {idx + 1}/{records}")

    prev_disabled = next_disabled = records == 0
    if idx == 0:
        prev_disabled = True
    if idx + 1 == records:
        next_disabled = True

    prev_col, next_col, _, delete_col = st.columns([3, 3, 4, 3])
    prev_col.button(
        "← Previous",
        disabled=prev_disabled,
        width="stretch",
        on_click=_update_record,
        kwargs={"direction": -1},
    )
    next_col.button(
        "Next →",
        disabled=next_disabled,
        width="stretch",
        on_click=_update_record,
        kwargs={"direction": 1},
    )
    delete_col.button(
        "⚠ Delete Q&A",
        type="tertiary",
        disabled=records == 1 or not is_authenticated(),
        width="stretch",
        on_click=_delete_record,
    )
    st.text_area("Question:", dataframe.loc[idx, "question"], key=f"runtime_q_{idx}")
    st.text_area("Answer:", dataframe.loc[idx, "reference_answer"], key=f"runtime_a_{idx}")
    st.text_area("Context:", dataframe.loc[idx, "reference_context"], disabled=True, height=68)
    st.text_input("Metadata:", dataframe.loc[idx, "metadata"], disabled=True)


def _create_gauge(value: float) -> Figure:
    """Create a correctness gauge for a percentage value."""
    gauge_value = min(max(value, 0.0), 100.0)
    figure = Figure(figsize=(8, 4), layout="constrained")
    axis = figure.subplots()

    for lower, upper, color in (
        (0, 75, "#d62728"),
        (75, 90, "#ffd700"),
        (90, 100, "#2ca02c"),
    ):
        axis.add_patch(
            Wedge(
                (0, 0),
                1,
                180 - upper * 1.8,
                180 - lower * 1.8,
                width=0.28,
                facecolor=color,
                edgecolor="white",
                linewidth=2,
            )
        )

    needle_angle = math.radians(180 - gauge_value * 1.8)
    axis.plot(
        [0, 0.78 * math.cos(needle_angle)],
        [0, 0.78 * math.sin(needle_angle)],
        color="#1f77b4",
        linewidth=4,
        solid_capstyle="round",
        zorder=4,
    )
    axis.add_patch(Circle((0, 0), 0.055, color="#1f77b4", zorder=5))

    for tick in (0, 75, 90, 100):
        tick_angle = math.radians(180 - tick * 1.8)
        axis.text(
            1.12 * math.cos(tick_angle),
            1.12 * math.sin(tick_angle),
            str(tick),
            ha="center",
            va="center",
            fontsize=10,
        )

    axis.text(0, 1.3, "Overall Correctness Score", ha="center", va="center", fontsize=20)
    axis.text(0, -0.18, f"{gauge_value:.0f}%", ha="center", va="center", fontsize=24, fontweight="bold")
    axis.set_xlim(-1.25, 1.25)
    axis.set_ylim(-0.35, 1.42)
    axis.set_aspect("equal")
    axis.axis("off")
    return figure


@st.dialog("Evaluation Report", width="large")
def _evaluation_report(eid: Optional[str] = None, report: Optional[dict] = None) -> None:
    """Display evaluation report dialog."""

    # Get the Report
    if eid:
        report = api_get("testbed/evaluation", params={"eid": eid})
    if report is None:
        st.error("No evaluation report available.")
        return

    # Settings
    st.subheader("Evaluation Settings")
    ll_settings = pd.DataFrame(report["settings"]["ll_model"], index=[0]).drop(
        ["chat_history", "max_input_tokens"], axis=1, errors="ignore"
    )
    st.dataframe(ll_settings.iloc[:, ::-1], hide_index=True)

    jm = report["settings"]["testbed"].get("judge_model")
    if jm:
        judge_str = f"{jm['provider']}/{jm['id']}" if isinstance(jm, dict) else str(jm)
        st.markdown(f"**Judge Model**: {judge_str}")

    # Backward compatibility: older reports lack vector_search.enabled
    vs_settings = report["settings"].get("vector_search", {})
    vs_enabled = vs_settings.get("enabled", "Vector Search" in report["settings"].get("tools_enabled", []))

    if vs_enabled:
        st.subheader("Vector Search Settings")
        st.markdown(
            f"""**Database**: {report["settings"]["database"]["alias"]};
            **Vector Store**: {vs_settings.get("vector_store", "Unspecified")}"""
        )
        embed_settings = pd.DataFrame(vs_settings, index=[0]).drop(
            ["vector_store", "alias", "enabled", "grade", "discovery", "rephrase"],
            axis=1,
            errors="ignore",
        )
        if vs_settings.get("search_type") == "Similarity":
            embed_settings.drop(["score_threshold", "fetch_k", "lambda_mult"], axis=1, inplace=True, errors="ignore")
        st.dataframe(embed_settings, hide_index=True)
    else:
        st.markdown("**Evaluated without Vector Search**")

    # Gauge
    st.pyplot(_create_gauge(float(report["correctness"]) * 100), width="stretch")

    # Correctness by Topic
    st.subheader("Correctness By Topic")
    by_topic = pd.DataFrame(report["correct_by_topic"])
    if not by_topic.empty:
        by_topic["correctness"] = pd.to_numeric(by_topic["correctness"], errors="coerce") * 100
        by_topic.rename(columns={"correctness": "Correctness %"}, inplace=True)
    st.dataframe(by_topic)

    # Failures
    st.subheader("Failures")
    failures = pd.DataFrame(report["failures"]).drop(
        ["conversation_history", "metadata", "correctness"], axis=1, errors="ignore"
    )
    if not failures.empty:
        st.dataframe(failures, hide_index=True)

    # Full Report
    st.subheader("Full Report")
    full_report = pd.DataFrame(report["report"]).drop(
        ["conversation_history", "metadata", "correctness"], axis=1, errors="ignore"
    )
    st.dataframe(full_report, hide_index=True)


#############################################################################
# Main Sections
#############################################################################
def _check_prerequisites() -> tuple[list, list, bool]:
    """Check prerequisites and return available models."""
    db_avail = _is_db_configured()
    if not db_avail:
        LOGGER.debug("Testbed Disabled (Database not configured)")
        st.error("Database is not configured. Disabling Testbed.", icon="🛑")

    ll_models_enabled = enabled_models_lookup("ll")
    available_ll_models = list(ll_models_enabled.keys())
    if not available_ll_models:
        st.error(
            "No OpenAI compatible language models are configured and/or enabled." + " Disabling Testing Framework.",
            icon="🛑",
        )

    if not db_avail or not available_ll_models:
        st.stop()

    # If no eligible Embedding Model; disable Generate Test Set
    gen_testset_disabled = False
    embed_models_enabled = enabled_models_lookup("embed")
    available_embed_models = list(embed_models_enabled.keys())
    if not available_embed_models:
        st.warning(
            "No embedding models are configured and/or enabled. Disabling Test Set Generation.",
            icon="⚠️",
        )
        gen_testset_disabled = True

    return available_ll_models, available_embed_models, gen_testset_disabled


def _setup_testbed_sources() -> list:
    """Determine available testset sources."""
    testset_sources = ["Database", "Local"]
    if "runtime_testbed_db_testsets" not in state or state.get("_core_unavailable"):
        try:
            _get_testbed_db_testsets.clear()
            state.runtime_testbed_db_testsets = _get_testbed_db_testsets()
            state.pop("_core_unavailable", None)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 503:
                state.runtime_testbed_db_testsets = []
                state["_core_unavailable"] = True
            else:
                raise
    if not state.runtime_testbed_db_testsets:
        testset_sources.remove("Database")
    if state.get("_core_unavailable"):
        st.warning("CORE database is not configured. Configure it in Settings > Databases.", icon="⚠️")
    return testset_sources


def _render_testset_generation_ui(available_ll_models: list, available_embed_models: list) -> dict:
    """Render test set generation UI and return parameters."""
    test_upload_file = st.file_uploader(
        (
            "Select one or more local PDF files to build a temporary Knowledge Base. "
            "It will be used to generate a synthetic Q&A Test Set."
        ),
        key=f"runtime_uploader_{state.runtime_testbed['uploader_key']}",
        accept_multiple_files=True,
        type=["pdf"],
    )

    col_left, col_center, col_right = st.columns([0.2, 0.35, 0.35])
    min_questions = max(1, len(test_upload_file))
    max_questions = max(100, min_questions)
    test_gen_questions = col_left.number_input(
        "Number of Q&A:",
        key="runtime_test_gen_questions",
        min_value=min_questions,
        max_value=max_questions,
        value=max(min_questions, 2),
    )

    testbed_settings = state["settings"]["client_settings"].get("testbed", {})

    # Q&A Language Model
    current_qa_ll = _model_identity_to_key(testbed_settings.get("qa_ll_model"))
    test_gen_llm = col_center.selectbox(
        "Q&A Language Model:",
        key="runtime_test_gen_llm",
        options=available_ll_models,
        index=selectbox_index(available_ll_models, current_qa_ll),
        on_change=lambda: _sync_testbed_model("qa_ll_model", "runtime_test_gen_llm"),
        help="Don't see your model? Unfortunately it is not currently supported by the testing framework.",
    )

    # Q&A Embedding Model
    current_qa_embed = _model_identity_to_key(testbed_settings.get("qa_embed_model"))
    test_gen_embed = col_right.selectbox(
        "Q&A Embedding Model:",
        key="runtime_test_gen_embed",
        options=available_embed_models,
        index=selectbox_index(available_embed_models, current_qa_embed),
        on_change=lambda: _sync_testbed_model("qa_embed_model", "runtime_test_gen_embed"),
        help="Don't see your model? Unfortunately it is not currently supported by the testing framework.",
    )

    return {
        "ll_model": test_gen_llm,
        "embed_model": test_gen_embed,
        "questions": test_gen_questions,
        "upload_file": test_upload_file,
    }


def _render_existing_testset_ui(testset_sources: list) -> tuple[Optional[str], str, bool, Optional[str]]:
    """Render existing testset selection UI."""
    testset_source = st.radio(
        "TestSet Source:",
        testset_sources,
        index=0,
        key="runtime_test_source",
        horizontal=True,
        on_change=_reset_testset,
        kwargs={"cache": True},
    )

    button_load_disabled = True
    endpoint = None
    selected_testset_id = None

    if testset_source == "Local":
        endpoint = "testbed/testset_load"
        test_upload_file = st.file_uploader(
            "Select a local, existing Q&A Test Set",
            key=f"runtime_uploader_{state.runtime_testbed['uploader_key']}",
            accept_multiple_files=True,
            type=["jsonl", "json"],
        )
        button_load_disabled = len(test_upload_file) == 0
    else:
        endpoint = "testbed/testset_qa"
        testset_list = [f"{item['name']} -- Created: {item['created']}" for item in state.runtime_testbed_db_testsets]
        current_db_testset = state.get("runtime_db_testset")
        if current_db_testset not in testset_list:
            testset_id = state.runtime_testbed.get("testset_id")
            if testset_id is not None:
                restored_label = next(
                    (
                        f"{item['name']} -- Created: {item['created']}"
                        for item in state.runtime_testbed_db_testsets
                        if item.get("tid") == testset_id
                    ),
                    None,
                )
                if restored_label:
                    state.runtime_db_testset = restored_label
                    current_db_testset = restored_label
        select_index = selectbox_index(testset_list, current_db_testset, default=0)
        db_testset = st.selectbox(
            "Test Set:",
            options=testset_list,
            index=select_index,
            key="runtime_db_testset",
            on_change=_reset_testset,
        )
        button_load_disabled = db_testset is None

        # Extract the testset_id when a database testset is selected
        if db_testset is not None:
            testset_name, testset_created = db_testset.split(" -- Created: ", 1)
            selected_testset_id = next(
                (
                    d["tid"]
                    for d in state.runtime_testbed_db_testsets
                    if d["name"] == testset_name and d["created"] == testset_created
                ),
                None,
            )

    return testset_source, endpoint, button_load_disabled, selected_testset_id


def _process_testset_request(endpoint: Optional[str], api_params: dict, testset_source: Optional[str] = None) -> None:
    """Process testset loading or generation request."""
    if endpoint is None:
        return
    try:
        with st.spinner("Processing Q&A... please be patient.", show_time=True):
            if testset_source != "Database":
                files = unique_file_payload(state[f"runtime_uploader_{state.runtime_testbed['uploader_key']}"])
                data = {"name": state.runtime_testbed["testset_name"]}
                extra_headers = None

                if endpoint == "testbed/testset_generate":
                    data.update(
                        {
                            "ll_model": api_params["ll_model"],
                            "embed_model": api_params["embed_model"],
                            "questions": str(api_params["questions"]),
                        }
                    )
                    extra_headers = {"client": state.optimizer_client}

                response = api_post(
                    endpoint,
                    files=files,
                    data=data,
                    extra_headers=extra_headers,
                    timeout=3600,
                )
                _get_testbed_db_testsets.clear()
                state.runtime_testbed_db_testsets = _get_testbed_db_testsets()
                state.runtime_testbed["testset_id"] = next(
                    (
                        d["tid"]
                        for d in state.runtime_testbed_db_testsets
                        if d.get("name") == state.runtime_testbed["testset_name"]
                    ),
                    None,
                )
            else:
                # Set required state from splitting selected DB TestSet
                testset_name, testset_created = state.runtime_db_testset.split(" -- Created: ", 1)
                state.runtime_testbed["testset_name"] = testset_name
                state.runtime_testbed["testset_id"] = next(
                    (
                        d["tid"]
                        for d in state.runtime_testbed_db_testsets
                        if d["name"] == testset_name and d["created"] == testset_created
                    ),
                    None,
                )
                response = api_get(endpoint, params={"tid": state.runtime_testbed["testset_id"]})
    except httpx.HTTPStatusError as exc:
        detail = extract_error_detail(exc)
        if isinstance(detail, dict) and "rejected_files" in detail:
            rejected = detail.get("rejected_files") or []
            lines = "\n".join(f"- **{r.get('filename', '?')}**: {r.get('reason', '')}" for r in rejected)
            st.error(
                f"Error Generating TestSet: {detail.get('message', 'Rejected files')}\n\n{lines}",
                icon="🚨",
            )
        else:
            st.error(f"Error Generating TestSet: {detail}", icon="🚨")
        st.stop()
    except (ValueError, KeyError, TypeError) as ex:
        LOGGER.error("Exception: %s", ex)
        st.error(f"Unexpected error: {ex}", icon="🚨")
        st.stop()

    try:
        state.runtime_testbed_qa = response["qa_data"]
        rejected = response.get("rejected_files") or []
        if rejected:
            details = "\n".join(f"- **{r['filename']}**: {r['reason']}" for r in rejected)
            st.warning(f"Skipped {len(rejected)} file(s) during generation:\n\n{details}", icon="⚠️")
        st.success(f"{len(state.runtime_testbed_qa)} Q&A Loaded.", icon="✅")
    except UnboundLocalError as ex:
        LOGGER.exception("Failed to load Tests: %s", ex)
        st.error("Unable to process Tests", icon="🚨")


def _render_evaluation_ui(available_ll_models: list) -> None:
    """Render evaluation section with sidebar and controls."""
    if "runtime_testbed_evaluations" not in state and state.runtime_testbed.get("testset_id"):
        state.runtime_testbed_evaluations = api_get(
            "testbed/evaluations",
            params={"tid": state.runtime_testbed["testset_id"]},
        )

    if state.get("runtime_testbed_evaluations"):
        st.subheader(f"Previous Evaluations for {state.runtime_new_testset_name}", divider="red")
        evaluations = {
            ev["eid"]: f"Evaluated: {ev['evaluated']} -- Correctness: {ev['correctness']}"
            for ev in state.runtime_testbed_evaluations
        }
        select, view = st.columns([9, 1])
        evaluation_eid = select.selectbox(
            "Previous Evaluations:",
            placeholder="-- Select --",
            label_visibility="collapsed",
            options=list(evaluations.keys()),
            format_func=lambda x: evaluations[x],
            key="runtime_evaluation_report",
        )
        view.button(
            "View",
            type="primary",
            width="stretch",
            on_click=_evaluation_report,
            kwargs={"eid": evaluation_eid},
            disabled=evaluation_eid is None,
        )

    st.subheader("Q&A Evaluation", divider="red")
    st.info("Use the sidebar settings for chatbot evaluation parameters", icon="⬅️")
    sidebar.toolkit_sidebar(show_vs_subtools=False)
    sidebar.lm_sidebar()
    sidebar.vector_search_sidebar()
    st.write("Choose a model to judge the correctness of the chatbot answer, then start evaluation.")

    col_left, col_center, _ = st.columns([4, 3, 3])

    testbed_settings = state["settings"]["client_settings"].get("testbed", {})
    current_judge = _model_identity_to_key(testbed_settings.get("judge_model"))
    col_left.selectbox(
        "Judge Language Model:",
        key="runtime_testbed_judge_model",
        options=available_ll_models,
        index=selectbox_index(available_ll_models, current_judge),
        label_visibility="collapsed",
        on_change=lambda: _sync_testbed_model("judge_model", "runtime_testbed_judge_model"),
    )

    if col_center.button(
        "Start Evaluation",
        type="primary",
        key="runtime_evaluate_button",
        help="Evaluation will automatically save the TestSet to the Database",
        on_click=_qa_update_db,
        disabled=not state.get("enable_client", True),
    ):
        try:
            with st.spinner("Starting Q&A evaluation... please be patient.", show_time=True):
                state.pop("runtime_testbed_evaluations", None)
                response = api_post(
                    "testbed/evaluate",
                    params={
                        "tid": state.runtime_testbed["testset_id"],
                        "judge": state.runtime_testbed_judge_model,
                    },
                    extra_headers={"client": state.optimizer_client},
                    timeout=1200,
                )
            st.success("Evaluation Complete!", icon="✅")

            if response:
                _evaluation_report(report=response)
        except httpx.HTTPStatusError as exc:
            st.error(extract_error_detail(exc), icon="🚨")


#############################################################################
# Entry Point
#############################################################################
def main() -> None:
    """Streamlit GUI"""
    # Testbed is a user workspace; only controls that change shared state for other
    # users are gated. See ``Scope`` in client/app/core/auth.py for the full policy.
    locked_notice()
    available_ll_models, available_embed_models, gen_testset_disabled = _check_prerequisites()
    testset_sources = _setup_testbed_sources()

    st.header("Testbed", divider="red")
    st.write(
        """
             Test Large Language and Embedding Configurations by generating or using an existing 'Test Set'.
             """
    )

    # Initialise testbed state
    if "runtime_testbed" not in state:
        state.runtime_testbed = {
            "uploader_key": random.randint(1, 100),
            "qa_index": 0,
            "testset_id": None,
            "testset_name": "".join(random.choices(string.ascii_letters, k=16)),
        }

    # Available/Compatible Model(s) found; continue
    st.toggle(
        "Generate Q&A Test Set",
        key="runtime_generate_test",
        value=False,
        disabled=gen_testset_disabled,
        on_change=_reset_testset,
        help="Create a new Test Set to be used for evaluation.",
    )

    # Load/Generate Test Set UI
    api_params = {}
    button_load_disabled = True
    button_text, endpoint, testset_source = None, None, None

    if not state.runtime_generate_test:
        st.subheader("Run Existing Q&A Test Set", divider="red")
        button_text = "Load Q&A"
        testset_source, endpoint, button_load_disabled, _ = _render_existing_testset_ui(testset_sources)
    else:
        st.subheader("Generate new Q&A Test Set", divider="red")
        button_text = "Generate Q&A"
        endpoint = "testbed/testset_generate"
        gen_params = _render_testset_generation_ui(available_ll_models, available_embed_models)
        api_params = {
            "ll_model": gen_params["ll_model"],
            "embed_model": gen_params["embed_model"],
            "questions": gen_params["questions"],
        }
        button_load_disabled = len(gen_params["upload_file"]) == 0

    # Disable button if QA already loaded
    button_load_disabled = button_load_disabled or "runtime_testbed_qa" in state

    col_left, col_center, _, col_right = st.columns([3, 3, 4, 3])

    if not button_load_disabled:
        state.runtime_testbed_running = "runtime_load_tests" in state and state.runtime_load_tests is True
    else:
        state.runtime_testbed_running = True

    if col_left.button(
        button_text,
        key="runtime_load_tests",
        width="stretch",
        disabled=state.runtime_testbed_running,
    ):
        assert endpoint is not None
        _process_testset_request(endpoint, api_params, testset_source)

    col_center.button(
        "Reset",
        key="runtime_reset_test_framework",
        type="primary",
        width="stretch",
        on_click=_reset_testset,
        kwargs={"cache": True},
    )
    col_right.button(
        "⚠ Delete Test Set",
        key="runtime_delete_test_set",
        type="tertiary",
        width="stretch",
        disabled=not state.runtime_testbed["testset_id"] or not is_authenticated(),
        on_click=_qa_delete,
    )

    # Show/Edit Q&A Tests
    if "runtime_testbed_qa" in state:
        st.subheader("Q&A Test Set Details", divider="red")
        st.text_input(
            "Test Set Name:",
            max_chars=20,
            key="runtime_new_testset_name",
            value=state.runtime_testbed["testset_name"],
            help="Update your Test Set a name to easily identify it later.",
            on_change=_qa_update_db,
        )
        _qa_update_gui(state.runtime_testbed_qa)
        testbed_qa_df = pd.DataFrame(state.runtime_testbed_qa)
        st.download_button(
            label="Download",
            data=testbed_qa_df.to_json(orient="records", indent=4),
            file_name=f"{state.runtime_new_testset_name}_testset.json",
            mime="application/json",
            on_click=_qa_update_db,
        )
        # Evaluator
        _render_evaluation_ui(available_ll_models)


main()
