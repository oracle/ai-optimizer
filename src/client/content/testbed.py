"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit, selectbox, testset, testsets, iloc, mult, selectai

import random
import string
import inspect
import json
from io import BytesIO
import plotly.graph_objects as go
import pandas as pd

import streamlit as st
from streamlit import session_state as state

from client.content.config.models import get_models

import client.utils.st_common as st_common
import client.utils.api_call as api_call
from client.utils.st_footer import remove_footer


import common.logging_config as logging_config

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
        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=value,
                title={"text": "Overall Correctness Score", "font": {"size": 42}},
                # Add the '%' suffix here
                number={"suffix": "%"},
                gauge={
                    "axis": {"range": [None, 100]},
                    "bar": {"color": "blue"},
                    "steps": [
                        {"range": [0, 75], "color": "red"},
                        {"range": [75, 90], "color": "yellow"},
                        {"range": [90, 100], "color": "green"},
                    ],
                    "threshold": {
                        "line": {"color": "blue", "width": 4},
                        "thickness": 0.75,
                        "value": 95,
                    },
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
    ll_settings.drop(["streaming", "chat_history"], axis=1, inplace=True)
    ll_settings_reversed = ll_settings.iloc[:, ::-1]
    st.dataframe(ll_settings_reversed, hide_index=True)
    if report["settings"]["vector_search"]["enabled"]:
        st.subheader("Vector Search Settings")
        st.markdown(f"""**Database**: {report["settings"]["database"]["alias"]};
            **Vector Store**: {report["settings"]["vector_search"]["vector_store"]}
        """)
        embed_settings = pd.DataFrame(report["settings"]["vector_search"], index=[0])
        embed_settings.drop(["vector_store", "alias", "enabled", "grading"], axis=1, inplace=True)
        if report["settings"]["vector_search"]["search_type"] == "Similarity":
            embed_settings.drop(["score_threshold", "fetch_k", "lambda_mult"], axis=1, inplace=True)
        st.dataframe(embed_settings, hide_index=True)
    else:
        st.markdown("**Evaluated without Vector Search**")

    # Show the Gauge
    gauge_fig = create_gauge(report["correctness"] * 100)
    # Display gauge
    st.plotly_chart(gauge_fig)

    # Correctness by Topic
    st.subheader("Correctness By Topic")
    by_topic = pd.DataFrame(report["correct_by_topic"])
    by_topic["correctness"] = by_topic["correctness"] * 100
    by_topic.rename(columns={"correctness": "Correctness %"}, inplace=True)
    st.dataframe(by_topic)

    # Failures
    st.subheader("Failures")
    failures = pd.DataFrame(report["failures"])
    failures.drop(["conversation_history", "metadata", "correctness"], axis=1, inplace=True)
    if not failures.empty:
        st.dataframe(failures, hide_index=True)

    # Full Report
    st.subheader("Full Report")
    full_report = pd.DataFrame(report["report"])
    full_report.drop(["conversation_history", "metadata", "correctness"], axis=1, inplace=True)
    st.dataframe(full_report, hide_index=True)

    # Download Button
    download_file("Download Report", report["html_report"], "evaluation_report.html", "text/html")


@st.cache_data
def get_testbed_db_testsets() -> dict:
    """Get Database TestSets; this is cached"""
    return api_call.get(endpoint="v1/testbed/testsets")


def qa_delete() -> None:
    """Delete QA from Database"""
    tid = state.testbed["testset_id"]
    api_call.delete(endpoint=f"v1/testbed/testset_delete/{tid}")
    st.success(f"Test Set and Evaluations Deleted: {state.testbed['testset_name']}")
    reset_testset(True)


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
    if state.testbed["qa_index"] != 0:
        state.testbed["qa_index"] += -1


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
        use_container_width=True,
        on_click=update_record,
        kwargs={"direction": -1},
    )
    next_col.button(
        "Next →",
        disabled=next_disabled,
        use_container_width=True,
        on_click=update_record,
        kwargs={"direction": 1},
    )
    delete_col.button(
        "⚠ Delete Q&A",
        type="tertiary",
        disabled=delete_disabled,
        use_container_width=True,
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
def main():
    """Streamlit GUI"""
    remove_footer()
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
    available_ll_models = [key for key, value in ll_models_enabled.items() if value.get("openai_compat")]
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
    available_embed_models = [key for key, value in embed_models_enabled.items() if value.get("openai_compat")]
    if not available_embed_models:
        st.warning(
            "No OpenAI compatible embedding models are configured and/or enabled. Disabling Test Set Generation.",
            icon="⚠️",
        )
        gen_testset_disabled = True

    testset_sources = ["Database", "Local"]
    if "testbed_db_testsets" not in state:
        state.testbed_db_testsets = get_testbed_db_testsets()
    if not state.testbed_db_testsets:
        testset_sources.remove("Database")

    #############################################################################
    # GUI
    #############################################################################
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
    api_params = {}
    ###################################
    # Load/Generate Test Set
    ###################################
    button_load_disabled = True
    button_text, endpoint, testset_source = None, None, None
    # Initialise the API Parameters (Increase Timeout)
    if not state.selected_generate_test:
        st.subheader("Run Existing Q&A Test Set", divider="red")
        button_text = "Load Q&A"
        testset_source = st.radio(
            "TestSet Source:",
            testset_sources,
            index=0,
            key="radio_test_source",
            horizontal=True,
            on_change=reset_testset,
            kwargs={"cache": True},
        )
        if testset_source == "Local":
            # Upload a TestSet from client host
            endpoint = "v1/testbed/testset_load"
            test_upload_file = st.file_uploader(
                "Select a local, existing Q&A Test Set",
                key=f"selected_uploader_{state.testbed['uploader_key']}",
                accept_multiple_files=True,
                type=["jsonl", "json"],
            )
            button_load_disabled = len(test_upload_file) == 0
        else:
            # Select existing TestSet from Database
            endpoint = "v1/testbed/testset_qa"
            testset_list = [f"{item['name']} -- Created: {item['created']}" for item in state.testbed_db_testsets]
            db_testset = st.selectbox(
                "Test Set:", options=testset_list, key="selected_db_testset", on_change=reset_testset
            )
            button_load_disabled = db_testset is None

    # Generate Test
    if state.selected_generate_test:
        st.subheader("Generate new Q&A Test Set", divider="red")
        button_text = "Generate Q&A"
        endpoint = "v1/testbed/testset_generate"
        test_upload_file = st.file_uploader(
            (
                "Select a local PDF file to build a temporary Knowledge Base. "
                "It will be used to generate a synthetic Q&A Test Set."
            ),
            key=f"selected_uploader_{state.testbed['uploader_key']}",
            accept_multiple_files=False,
            type="pdf",
        )
        button_load_disabled = test_upload_file is None
        col_left, col_center, col_right = st.columns([0.2, 0.35, 0.35])
        test_gen_questions = col_left.number_input(
            "Number of Q&A:",
            key="selected_test_gen_questions",
            min_value=1,
            max_value=100,
            value=2,
        )
        test_gen_llm = col_center.selectbox(
            "Q&A Language Model:",
            key="selected_test_gen_llm",
            options=available_ll_models,
            index=0,
            help="Don't see your model? Unfortunately it is not currently supported by the testing framework.",
        )
        test_gen_embed = col_right.selectbox(
            "Q&A Embedding Model:",
            key="selected_test_gen_embed",
            options=available_embed_models,
            index=0,
            help="Don't see your model? Unfortunately it is not currently supported by the testing framework.",
        )
        api_params = {
            "ll_model": test_gen_llm,
            "embed_model": test_gen_embed,
            "questions": test_gen_questions,
        }
    # Process Q&A Request
    button_load_disabled = button_load_disabled or state.testbed["testset_id"] == "" or "testbed_qa" in state
    col_left, col_center, _, col_right = st.columns([3, 3, 4, 3])
    if not button_load_disabled:
        if "load_tests" in state and state.load_tests is True:
            state.running = True
        else:
            state.running = False
    else:
        state.running = True

    # Load TestSets (and Evaluations if from DB)
    if col_left.button(button_text, key="load_tests", use_container_width=True, disabled=state.running):
        placeholder = st.empty()
        with st.spinner("Processing Q&A... please be patient.", show_time=True):
            if testset_source != "Database":
                api_params["name"] = (state.testbed["testset_name"],)
                files = st_common.local_file_payload(state[f"selected_uploader_{state.testbed['uploader_key']}"])
                api_payload = {"files": files}
                try:
                    response = api_call.post(endpoint=endpoint, params=api_params, payload=api_payload, timeout=3600)
                    get_testbed_db_testsets.clear()
                    state.testbed_db_testsets = get_testbed_db_testsets()
                    state.testbed["testset_id"] = next(
                        (
                            d["tid"]
                            for d in state.testbed_db_testsets
                            if d.get("name") == state.testbed["testset_name"]
                        ),
                        None,
                    )
                except api_call.ApiError as ex:
                    st.error(f"Error Generating TestSet: {ex}", icon="🚨")
                    st.stop()
                except Exception as ex:
                    logger.error("Exception: %s", ex)
                    st.error(f"Looks like you found a bug: {ex}", icon="🚨")
                    st.stop()
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
        try:
            state.testbed_qa = response["qa_data"]
            st.success(f"{len(state.testbed_qa)} Q&A Loaded.", icon="✅")
        except UnboundLocalError as ex:
            logger.exception("Failed to load Tests: %s", ex)
            st.error("Unable to process Tests", icon="🚨")
    col_center.button(
        "Reset",
        key="reset_test_framework",
        type="primary",
        use_container_width=True,
        on_click=reset_testset,
        kwargs={"cache": True},
    )
    col_right.button(
        "⚠ Delete Test Set",
        key="delete_test_set",
        type="tertiary",
        use_container_width=True,
        disabled=not state.testbed["testset_id"],
        on_click=qa_delete,
    )

    ###################################
    # Show/Edit Q&A Tests
    ###################################
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
        ###################################
        # Evaluator
        ###################################
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
                use_container_width=True,
                on_click=evaluation_report,
                kwargs={"eid": evaluation_eid},
                disabled=evaluation_eid is None,
            )

        st.subheader("Q&A Evaluation", divider="red")
        st.info("Use the sidebar settings for chatbot evaluation parameters", icon="⬅️")
        st_common.tools_sidebar()
        st_common.ll_sidebar()
        st_common.selectai_sidebar()
        st_common.vector_search_sidebar()
        st.write("Choose a model to judge the correctness of the chatbot answer, then start evaluation.")
        col_left, col_center, _ = st.columns([3, 3, 4])
        col_left.selectbox(
            "Judge Language Model:",
            key="selected_evaluate_judge",
            options=available_ll_models,
            index=0,
            label_visibility="collapsed",
        )
        if col_center.button(
            "Start Evaluation",
            type="primary",
            key="evaluate_button",
            help="Evaluation will automatically save the TestSet to the Database",
            on_click=qa_update_db,
        ):
            with st.spinner("Starting Q&A evaluation... please be patient.", show_time=True):
                st_common.clear_state_key("testbed_evaluations")
                st_common.patch_settings()
                endpoint = "v1/testbed/evaluate"
                api_params = {"tid": state.testbed["testset_id"], "judge": state.selected_evaluate_judge}
                evaluate = api_call.post(endpoint=endpoint, params=api_params, timeout=1200)
            st.success("Evaluation Complete!", icon="✅")

            ###################################
            # Results
            ###################################
            if evaluate:
                evaluation_report(report=evaluate)


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
