"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore mult selectbox testset testsets

import random
import string
import inspect
import json
from io import BytesIO
import plotly.graph_objects as go
import pandas as pd

import streamlit as st
from streamlit import session_state as state

from client.content.config.tabs.models import get_models

from client.utils import st_common, api_call

from common import logging_config

logger = logging_config.logging.getLogger("client.content.testbed")


#####################################################
# Functions
#####################################################
def reset_testset(cache: bool = False) -> None:
    """Clear all Test Set Data"""
    st_common.clear_state_key("testbed")
    st_common.clear_state_key("selected_testset_name")
    st_common.clear_state_key("testbed_qa")
    st_common.clear_state_key("testbed_db_testsets")
    st_common.clear_state_key("testbed_evaluations")
    if cache:
        get_testbed_db_testsets.clear()


@st.fragment()
def download_file(label, data, file_name, mime):
    """Download HTML Report - Here as a fragment to prevent a page-reload"""
    st.download_button(label=label, data=data, file_name=file_name, mime=mime)


@st.dialog("Evaluation Report", width="large")
def evaluation_report(eid=None, report=None) -> None:
    """Dialog Box with Evaluation Report"""

    def create_gauge(value):
        """Create the GUI Gauge"""
        # Workaround for Plotly bug: use 0.1 to ensure needle visibility
        gauge_value = max(0.1, value) if value < 1 else value

        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=gauge_value,
                title={"text": "Overall Correctness Score", "font": {"size": 42}},
                number={"suffix": "%", "valueformat": ".0f"},  # Round to whole number
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "blue"},
                    "steps": [
                        {"range": [0, 75], "color": "red"},
                        {"range": [75, 90], "color": "yellow"},
                        {"range": [90, 100], "color": "green"},
                    ],
                    # REMOVED threshold - it seems to be causing the needle to jump to wrong position
                },
            )
        )

        return fig

    # Get the Report
    if eid:
        report = api_call.get(endpoint="v1/testbed/evaluation", params={"eid": eid})
    # Settings
    st.subheader("Evaluation Settings")
    ll_settings = pd.DataFrame(report["settings"]["ll_model"], index=[0])
    ll_settings.drop(["chat_history", "max_input_tokens"], axis=1, inplace=True)
    ll_settings_reversed = ll_settings.iloc[:, ::-1]
    st.dataframe(ll_settings_reversed, hide_index=True)
    if report["settings"]["testbed"]["judge_model"]:
        st.markdown(f"**Judge Model**: {report['settings']['testbed']['judge_model']}")
    # if discovery; then list out the tables that were discovered (MCP implementation)
    # if report["settings"]["vector_search"].get("discovery"):
    if report["settings"]["vector_search"]["enabled"]:
        st.subheader("Vector Search Settings")
        st.markdown(f"""**Database**: {report["settings"]["database"]["alias"]};
            **Vector Store**: {report["settings"]["vector_search"]["vector_store"]}
        """)
        embed_settings = pd.DataFrame(report["settings"]["vector_search"], index=[0])
        fields_to_drop = ["vector_store", "alias", "enabled", "grading"]
        existing_fields = [f for f in fields_to_drop if f in embed_settings.columns]
        if existing_fields:
            embed_settings.drop(existing_fields, axis=1, inplace=True)
        if report["settings"]["vector_search"]["search_type"] == "Similarity":
            embed_settings.drop(["score_threshold", "fetch_k", "lambda_mult"], axis=1, inplace=True)
        st.dataframe(embed_settings, hide_index=True)
    else:
        st.markdown("**Evaluated without Vector Search**")

    # Show the Gauge
    correctness_value = report["correctness"]
    percentage_value = correctness_value * 100

    # Debug output to verify the value
    st.write(f"Debug: Raw correctness = {correctness_value}, Percentage = {percentage_value:.2f}%")

    gauge_fig = create_gauge(percentage_value)
    # Display gauge
    st.plotly_chart(gauge_fig)

    # Correctness by Topic
    st.subheader("Correctness By Topic")
    by_topic = pd.DataFrame(report["correct_by_topic"])
    if not by_topic.empty:
        by_topic["correctness"] = by_topic["correctness"] * 100
        by_topic.rename(columns={"correctness": "Correctness %"}, inplace=True)
    st.dataframe(by_topic)

    # Failures
    st.subheader("Failures")
    failures = pd.DataFrame(report["failures"])
    failures.drop(["conversation_history", "metadata", "correctness"], axis=1, inplace=True, errors="ignore")
    if not failures.empty:
        st.dataframe(failures, hide_index=True)

    # Full Report
    st.subheader("Full Report")
    full_report = pd.DataFrame(report["report"])
    full_report.drop(["conversation_history", "metadata", "correctness"], axis=1, inplace=True, errors="ignore")
    st.dataframe(full_report, hide_index=True)

    # Download Button
    # download_file("Download Report", report["html_report"], "evaluation_report.html", "text/html") #CDB


@st.cache_data(show_spinner="Retrieving TestSets")
def get_testbed_db_testsets() -> dict:
    """Get Database TestSets; this is cached"""
    return api_call.get(endpoint="v1/testbed/testsets")


def qa_delete() -> None:
    """Delete QA from Database"""
    tid = state.testbed["testset_id"]
    try:
        api_call.delete(endpoint=f"v1/testbed/testset_delete/{tid}")
        st.success(f"Test Set and Evaluations Deleted: {state.testbed['testset_name']}")
        reset_testset(True)
    except api_call.ApiError as e:
        st.error(f"Failed to delete test set: {e.message}")


def qa_update_db() -> None:
    """Update QA in Database"""
    update_record(0)  # Ensure any changes made to current record are recorded
    endpoint = "v1/testbed/testset_load"
    api_params = {
        "name": state.selected_new_testset_name,
        "tid": state.testbed["testset_id"],
    }
    json_data = json.dumps(state.testbed_qa)

    qa_file = BytesIO(json_data.encode("utf-8"))
    api_payload = {"files": [("files", ("data.json", qa_file, "application/json"))]}
    _ = api_call.post(endpoint=endpoint, params=api_params, payload=api_payload, timeout=120)
    st_common.clear_state_key("testbed_db_testsets")
    get_testbed_db_testsets.clear()
    state.testbed_db_testsets = get_testbed_db_testsets()


@st.fragment()
def update_record(direction: int = 0) -> None:
    """Update streamlit state with record changes"""
    state.testbed_qa[state.testbed["qa_index"]]["question"] = state[f"selected_q_{state.testbed['qa_index']}"]
    state.testbed_qa[state.testbed["qa_index"]]["reference_answer"] = state[f"selected_a_{state.testbed['qa_index']}"]
    state.testbed["qa_index"] += direction


@st.fragment()
def delete_record() -> None:
    """Delete record from streamlit state"""
    state.testbed_qa.pop(state.testbed["qa_index"])
    # After deletion, ensure index points to a valid record
    if len(state.testbed_qa) > 0:
        # If there are records remaining, ensure index is within bounds
        if state.testbed["qa_index"] >= len(state.testbed_qa):
            # Index is now out of bounds, point to last record
            state.testbed["qa_index"] = len(state.testbed_qa) - 1
    else:
        # List is empty, reset index to 0
        state.testbed["qa_index"] = 0


def qa_update_gui(qa_testset: list) -> None:
    """Update Q&A Records in GUI"""
    dataframe = pd.DataFrame(qa_testset)
    records = dataframe.shape[0]
    delete_disabled = False
    if records == 1:
        delete_disabled = True
    st.write("Record: " + str(state.testbed["qa_index"] + 1) + "/" + str(records))

    prev_disabled = next_disabled = records == 0
    if state.testbed["qa_index"] == 0:
        prev_disabled = True
    if state.testbed["qa_index"] + 1 == records:
        next_disabled = True
    prev_col, next_col, _, delete_col = st.columns([3, 3, 4, 3])
    prev_col.button(
        "← Previous",
        disabled=prev_disabled,
        width="stretch",
        on_click=update_record,
        kwargs={"direction": -1},
    )
    next_col.button(
        "Next →",
        disabled=next_disabled,
        width="stretch",
        on_click=update_record,
        kwargs={"direction": 1},
    )
    delete_col.button(
        "⚠ Delete Q&A",
        type="tertiary",
        disabled=delete_disabled,
        width="stretch",
        on_click=delete_record,
    )
    st.text_area(
        "Question:",
        dataframe.loc[state.testbed["qa_index"], "question"],
        key=f"selected_q_{state.testbed['qa_index']}",
    )
    st.text_area(
        "Answer:",
        dataframe.loc[state.testbed["qa_index"], "reference_answer"],
        key=f"selected_a_{state.testbed['qa_index']}",
    )
    st.text_area(
        "Context:",
        dataframe.loc[state.testbed["qa_index"], "reference_context"],
        disabled=True,
        height=68,
    )
    st.text_input("Metadata:", dataframe.loc[state.testbed["qa_index"], "metadata"], disabled=True)


#############################################################################
# MAIN
#############################################################################
def check_prerequisites() -> tuple[list, list, bool]:
    """Check if prerequisites are met and return configuration data"""
    try:
        get_models()
    except api_call.ApiError:
        st.stop()

    db_avail = st_common.is_db_configured()
    if not db_avail:
        logger.debug("Testbed Disabled (Database not configured)")
        st.error("Database is not configured. Disabling Testbed.", icon="🛑")

    # If there is no eligible (OpenAI Compat.) LL Models; then disable ALL functionality
    ll_models_enabled = st_common.enabled_models_lookup("ll")
    available_ll_models = [key for key, value in ll_models_enabled.items()]
    if not available_ll_models:
        st.error(
            "No OpenAI compatible language models are configured and/or enabled. Disabling Testing Framework.",
            icon="🛑",
        )

    if not db_avail or not available_ll_models:
        st.stop()

    # If there is no eligible (OpenAI Compat.) Embedding Model; disable Generate Test Set
    gen_testset_disabled = False
    embed_models_enabled = st_common.enabled_models_lookup("embed")
    # Remove oci/cohere* models as not supported by LiteLLM
    available_embed_models = [
        key
        for key, value in embed_models_enabled.items()
        if not (value.get("provider") == "oci" and "cohere" in value.get("id", ""))
    ]
    if not available_embed_models:
        st.warning(
            "No OpenAI compatible embedding models are configured and/or enabled. Disabling Test Set Generation.",
            icon="⚠️",
        )
        gen_testset_disabled = True

    return available_ll_models, available_embed_models, gen_testset_disabled


def setup_testbed_sources() -> list:
    """Setup and return available testset sources"""
    testset_sources = ["Database", "Local"]
    if "testbed_db_testsets" not in state:
        state.testbed_db_testsets = get_testbed_db_testsets()
    if not state.testbed_db_testsets:
        testset_sources.remove("Database")
    return testset_sources


def render_testset_generation_ui(available_ll_models: list, available_embed_models: list) -> dict:
    """Render test set generation UI and return parameters"""
    test_upload_file = st.file_uploader(
        (
            "Select a local PDF file to build a temporary Knowledge Base. "
            "It will be used to generate a synthetic Q&A Test Set."
        ),
        key=f"selected_uploader_{state.testbed['uploader_key']}",
        accept_multiple_files=False,
        type="pdf",
    )

    col_left, col_center, col_right = st.columns([0.2, 0.35, 0.35])
    test_gen_questions = col_left.number_input(
        "Number of Q&A:",
        key="selected_test_gen_questions",
        min_value=1,
        max_value=100,
        value=2,
    )

    if state.client_settings["testbed"].get("qa_ll_model") is None:
        state.client_settings["testbed"]["qa_ll_model"] = available_ll_models[0]
    selected_qa_ll_model = state.client_settings["testbed"]["qa_ll_model"]
    qa_ll_model_idx = available_ll_models.index(selected_qa_ll_model)
    test_gen_llm = col_center.selectbox(
        "Q&A Language Model:",
        key="selected_test_gen_llm",
        options=available_ll_models,
        index=qa_ll_model_idx,
        on_change=st_common.update_client_settings("testbed"),
        help="Don't see your model? Unfortunately it is not currently supported by the testing framework.",
    )

    if state.client_settings["testbed"].get("qa_embed_model") is None:
        state.client_settings["testbed"]["qa_embed_model"] = available_embed_models[0]
    selected_qa_embed_model = state.client_settings["testbed"]["qa_embed_model"]
    qa_embed_model_idx = available_embed_models.index(selected_qa_embed_model)
    test_gen_embed = col_right.selectbox(
        "Q&A Embedding Model:",
        key="selected_test_gen_embed",
        options=available_embed_models,
        index=qa_embed_model_idx,
        on_change=st_common.update_client_settings("testbed"),
        help="Don't see your model? Unfortunately it is not currently supported by the testing framework.",
    )

    return {
        "ll_model": test_gen_llm,
        "embed_model": test_gen_embed,
        "questions": test_gen_questions,
        "upload_file": test_upload_file,
    }


def render_existing_testset_ui(testset_sources: list) -> tuple[str, str, bool, str]:
    """Render existing testset UI and return configuration"""
    testset_source = st.radio(
        "TestSet Source:",
        testset_sources,
        index=0,
        key="radio_test_source",
        horizontal=True,
        on_change=reset_testset,
        kwargs={"cache": True},
    )

    button_load_disabled = True
    endpoint = None
    selected_testset_id = None

    if testset_source == "Local":
        endpoint = "v1/testbed/testset_load"
        test_upload_file = st.file_uploader(
            "Select a local, existing Q&A Test Set",
            key=f"selected_uploader_{state.testbed['uploader_key']}",
            accept_multiple_files=True,
            type=["jsonl", "json"],
        )
        button_load_disabled = len(test_upload_file) == 0
    else:
        endpoint = "v1/testbed/testset_qa"
        testset_list = [f"{item['name']} -- Created: {item['created']}" for item in state.testbed_db_testsets]
        db_testset = st.selectbox(
            "Test Set:", options=testset_list, key="selected_db_testset", on_change=reset_testset
        )
        button_load_disabled = db_testset is None

        # Extract the testset_id when a database testset is selected
        if db_testset is not None:
            testset_name, testset_created = db_testset.split(" -- Created: ", 1)
            selected_testset_id = next(
                (
                    d["tid"]
                    for d in state.testbed_db_testsets
                    if d["name"] == testset_name and d["created"] == testset_created
                ),
                None,
            )

    return testset_source, endpoint, button_load_disabled, selected_testset_id


def process_testset_request(endpoint: str, api_params: dict, testset_source: str = None) -> None:
    """Process testset loading/generation request"""
    try:
        with st.spinner("Processing Q&A... please be patient.", show_time=True):
            if testset_source != "Database":
                api_params["name"] = state.testbed["testset_name"]
                files = st_common.local_file_payload(state[f"selected_uploader_{state.testbed['uploader_key']}"])
                api_payload = {"files": files}
                response = api_call.post(endpoint=endpoint, params=api_params, payload=api_payload, timeout=3600)
                get_testbed_db_testsets.clear()
                state.testbed_db_testsets = get_testbed_db_testsets()
                state.testbed["testset_id"] = next(
                    (d["tid"] for d in state.testbed_db_testsets if d.get("name") == state.testbed["testset_name"]),
                    None,
                )
            else:
                # Set required state from splitting selected DB TestSet
                testset_name, testset_created = state.selected_db_testset.split(" -- Created: ", 1)
                state.testbed["testset_name"] = testset_name
                state.testbed["testset_id"] = next(
                    (
                        d["tid"]
                        for d in state.testbed_db_testsets
                        if d["name"] == testset_name and d["created"] == testset_created
                    ),
                    None,
                )
                api_params = {"tid": state.testbed["testset_id"]}
                # Retrieve TestSet Data
                response = api_call.get(endpoint=endpoint, params=api_params)
    except api_call.ApiError as ex:
        st.error(f"Error Generating TestSet: {ex}", icon="🚨")
        st.stop()
    except (ValueError, KeyError, TypeError) as ex:
        logger.error("Exception: %s", ex)
        st.error(f"Looks like you found a bug: {ex}", icon="🚨")
        st.stop()

    try:
        state.testbed_qa = response["qa_data"]
        st.success(f"{len(state.testbed_qa)} Q&A Loaded.", icon="✅")
    except UnboundLocalError as ex:
        logger.exception("Failed to load Tests: %s", ex)
        st.error("Unable to process Tests", icon="🚨")


def render_evaluation_ui(available_ll_models: list) -> None:
    """Render evaluation UI and handle evaluation"""
    if "testbed_evaluations" not in state and "testset_id" in state.testbed and state.testbed["testset_id"]:
        # Retrieve Evaluations
        api_params = {"tid": state.testbed["testset_id"]}
        endpoint = "v1/testbed/evaluations"
        state.testbed_evaluations = api_call.get(endpoint=endpoint, params=api_params)

    if state.testbed_evaluations:
        st.subheader(f"Previous Evaluations for {state.selected_new_testset_name}", divider="red")
        evaluations = {
            evaluation["eid"]: f"Evaluated: {evaluation['evaluated']} -- Correctness: {evaluation['correctness']}"
            for evaluation in state.testbed_evaluations
        }
        select, view = st.columns([9, 1])
        evaluation_eid = select.selectbox(
            "Previous Evaluations:",
            placeholder="-- Select --",
            label_visibility="collapsed",
            options=list(evaluations.keys()),
            format_func=lambda x: evaluations[x],
            key="selected_evaluation_report",
        )
        view.button(
            "View",
            type="primary",
            width="stretch",
            on_click=evaluation_report,
            kwargs={"eid": evaluation_eid},
            disabled=evaluation_eid is None,
        )

    st.subheader("Q&A Evaluation", divider="red")
    st.info("Use the sidebar settings for chatbot evaluation parameters", icon="⬅️")
    st_common.tools_sidebar()
    st_common.ll_sidebar()
    st_common.vector_search_sidebar()
    st.write("Choose a model to judge the correctness of the chatbot answer, then start evaluation.")
    col_left, col_center, _ = st.columns([4, 3, 3])

    if state.client_settings["testbed"].get("judge_model") is None:
        state.client_settings["testbed"]["judge_model"] = available_ll_models[0]
    selected_judge = state.client_settings["testbed"]["judge_model"]
    judge_idx = available_ll_models.index(selected_judge)
    col_left.selectbox(
        "Judge Language Model:",
        key="selected_testbed_judge_model",
        options=available_ll_models,
        index=judge_idx,
        label_visibility="collapsed",
        on_change=st_common.update_client_settings("testbed"),
    )

    # Check if vector search is enabled but no vector store is selected
    evaluation_disabled = False
    if state.client_settings.get("vector_search", {}).get("enabled", False):
        # If vector search is enabled, check if a vector store is selected
        if not state.client_settings.get("vector_search", {}).get("vector_store"):
            evaluation_disabled = True

    if col_center.button(
        "Start Evaluation",
        type="primary",
        key="evaluate_button",
        help="Evaluation will automatically save the TestSet to the Database",
        on_click=qa_update_db,
        disabled=evaluation_disabled,
    ):
        with st.spinner("Starting Q&A evaluation... please be patient.", show_time=True):
            st_common.clear_state_key("testbed_evaluations")
            st_common.patch_settings()
            endpoint = "v1/testbed/evaluate"
            api_params = {"tid": state.testbed["testset_id"], "judge": state.selected_testbed_judge_model}
            evaluate = api_call.post(endpoint=endpoint, params=api_params, timeout=1200)
        st.success("Evaluation Complete!", icon="✅")

        if evaluate:
            evaluation_report(report=evaluate)


def main() -> None:
    """Streamlit GUI"""
    available_ll_models, available_embed_models, gen_testset_disabled = check_prerequisites()
    testset_sources = setup_testbed_sources()

    st.header("Testbed", divider="red")
    st.write("""
             Test Large Language and Embedding Configurations by generating or using an existing 'Test Set'.
             """)

    # Initialise the testbed state
    if "testbed" not in state:
        state.testbed = {
            "uploader_key": random.randint(1, 100),
            "qa_index": 0,
            "testset_id": None,
            "testset_name": "".join(random.choices(string.ascii_letters, k=16)),
        }

    # Available/Compatible Model(s) found; continue
    st.toggle(
        "Generate Q&A Test Set",
        key="selected_generate_test",
        value=False,
        disabled=gen_testset_disabled,
        on_change=reset_testset,
        help="Create a new Test Set to be used for evaluation.",
    )

    # Load/Generate Test Set UI
    api_params = {}
    button_load_disabled = True
    button_text, endpoint, testset_source = None, None, None

    if not state.selected_generate_test:
        st.subheader("Run Existing Q&A Test Set", divider="red")
        button_text = "Load Q&A"
        testset_source, endpoint, button_load_disabled, _ = render_existing_testset_ui(testset_sources)
    else:
        st.subheader("Generate new Q&A Test Set", divider="red")
        button_text = "Generate Q&A"
        endpoint = "v1/testbed/testset_generate"
        gen_params = render_testset_generation_ui(available_ll_models, available_embed_models)
        api_params = {
            "ll_model": gen_params["ll_model"],
            "embed_model": gen_params["embed_model"],
            "questions": gen_params["questions"],
        }
        button_load_disabled = gen_params["upload_file"] is None

    # Process Q&A Request buttons
    # Only check testset_id when loading existing test sets, not when generating new ones
    if not state.selected_generate_test:
        # Use the selected_testset_id from the UI instead of state.testbed["testset_id"]
        # since state.testbed["testset_id"] is only set after loading
        button_load_disabled = button_load_disabled or "testbed_qa" in state
    else:
        button_load_disabled = button_load_disabled or "testbed_qa" in state
    col_left, col_center, _, col_right = st.columns([3, 3, 4, 3])

    if not button_load_disabled:
        state.running = "load_tests" in state and state.load_tests is True
    else:
        state.running = True

    if col_left.button(button_text, key="load_tests", width="stretch", disabled=state.running):
        process_testset_request(endpoint, api_params, testset_source)

    col_center.button(
        "Reset",
        key="reset_test_framework",
        type="primary",
        width="stretch",
        on_click=reset_testset,
        kwargs={"cache": True},
    )
    col_right.button(
        "⚠ Delete Test Set",
        key="delete_test_set",
        type="tertiary",
        width="stretch",
        disabled=not state.testbed["testset_id"],
        on_click=qa_delete,
    )

    # Show/Edit Q&A Tests
    if "testbed_qa" in state:
        st.subheader("Q&A Test Set Details", divider="red")
        st.text_input(
            "Test Set Name:",
            max_chars=20,
            key="selected_new_testset_name",
            value=state.testbed["testset_name"],
            help="Update your Test Set a name to easily identify it later.",
            on_change=qa_update_db,
        )
        qa_update_gui(state.testbed_qa)
        testbed_qa_df = pd.DataFrame(state.testbed_qa)
        st.download_button(
            label="Download",
            data=testbed_qa_df.to_json(orient="records", indent=4),
            file_name=f"{state.selected_new_testset_name}_testset.json",
            mime="application/json",
            on_click=qa_update_db,
        )
        # Evaluator
        render_evaluation_ui(available_ll_models)


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
