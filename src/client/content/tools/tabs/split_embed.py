"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes is used for the splitting and chunking process using Streamlit (`st`).
"""
# spell-checker:ignore selectbox hnsw ivf ocids iterrows

import math
import re

import pandas as pd

import streamlit as st
from streamlit import session_state as state

from client.utils import api_call, st_common

from client.content.config.tabs.databases import get_databases
from client.content.config.tabs.models import get_models
from client.content.config.tabs.oci import get_oci

from common.schema import DistanceMetrics, IndexTypes, DatabaseVectorStorage
from common import logging_config, help_text, functions

logger = logging_config.logging.getLogger("client.tools.tabs.split_embed")


#####################################################
# Functions
#####################################################
@st.cache_data(show_spinner="Retrieving OCI Compartments")
def get_compartments() -> dict:
    """Get OCI Compartments; function for Streamlit caching"""
    response = api_call.get(endpoint=f"v1/oci/compartments/{state.client_settings['oci']['auth_profile']}")
    return response


def get_buckets(compartment: str) -> list:
    """Get OCI Buckets in selected compartment; function for Streamlit caching"""
    try:
        response = api_call.get(
            endpoint=f"v1/oci/buckets/{compartment}/{state.client_settings['oci']['auth_profile']}"
        )
    except api_call.ApiError:
        response = ["No Access to Buckets in this Compartment"]
    return response


def get_bucket_objects(bucket: str) -> list:
    """Get OCI Buckets in selected compartment; function for Streamlit caching"""
    response = api_call.get(endpoint=f"v1/oci/objects/{bucket}/{state.client_settings['oci']['auth_profile']}")
    return response


@st.cache_resource
def files_data_frame(objects, process=False):
    """Produce a data frame of files"""
    files = pd.DataFrame({"File": [], "Process": []})
    if len(objects) >= 1:
        files = pd.DataFrame(
            {"File": [objects[0]], "Process": [process]},
        )
        for file in objects[1:]:
            new_record = pd.DataFrame([{"File": file, "Process": process}])
            files = pd.concat([files, new_record], ignore_index=True)
    return files


def files_data_editor(files, key):
    """Edit data frame"""
    return st.data_editor(
        files,
        key=key,
        width="stretch",
        column_config={
            "to process": st.column_config.CheckboxColumn(
                "in",
                help="Select files **to include** into loading process",
                default=False,
            )
        },
        disabled=["File"],
        hide_index=True,
    )


def update_chunk_overlap_slider() -> None:
    """Keep text and slider input aligned"""
    state.selected_chunk_overlap_slider = state.selected_chunk_overlap_input


def update_chunk_overlap_input() -> None:
    """Keep text and slider input aligned"""
    state.selected_chunk_overlap_input = state.selected_chunk_overlap_slider


def update_chunk_size_slider() -> None:
    """Keep text and slider input aligned"""
    state.selected_chunk_size_slider = state.selected_chunk_size_input


def update_chunk_size_input() -> None:
    """Keep text and slider input aligned"""
    state.selected_chunk_size_input = state.selected_chunk_size_slider


#############################################################################
# Helper Functions
#############################################################################
def _render_embedding_configuration(embed_models_enabled: dict, embed_request: DatabaseVectorStorage) -> None:
    """Render the embedding configuration section"""
    st.header("Embedding Configuration", divider="red")
    embed_request.model = st.selectbox(
        "Embedding models available: ",
        options=list(embed_models_enabled.keys()),
        index=0,
        key="selected_embed_model",
    )
    embed_url = embed_models_enabled[embed_request.model]["api_base"]
    st.write(f"Embedding Server: {embed_url}")
    is_embed_accessible, embed_err_msg = functions.is_url_accessible(embed_url)
    if not is_embed_accessible:
        st.warning(embed_err_msg, icon="⚠️")
        if st.button("Retry"):
            st.rerun()
        st.stop()

    chunk_size_max = embed_models_enabled[embed_request.model]["max_chunk_size"]
    col1_1, col1_2 = st.columns([0.8, 0.2])
    with col1_1:
        st.slider(
            "Chunk Size (tokens):",
            min_value=0,
            max_value=chunk_size_max,
            value=chunk_size_max,
            key="selected_chunk_size_slider",
            on_change=update_chunk_size_input,
            help=help_text.help_dict["chunk_size"],
        )
        st.slider(
            "Chunk Overlap (% of Chunk Size)",
            min_value=0,
            max_value=100,
            value=20,
            step=5,
            key="selected_chunk_overlap_slider",
            on_change=update_chunk_overlap_input,
            format="%d%%",
            help=help_text.help_dict["chunk_overlap"],
        )

    with col1_2:
        embed_request.chunk_size = st.number_input(
            "Chunk Size (tokens):",
            label_visibility="hidden",
            min_value=0,
            max_value=chunk_size_max,
            value=chunk_size_max,
            key="selected_chunk_size_input",
            on_change=update_chunk_size_slider,
        )
        chunk_overlap_pct = st.number_input(
            "Chunk Overlap (% of Chunk Size):",
            label_visibility="hidden",
            min_value=0,
            max_value=100,
            value=20,
            step=5,
            key="selected_chunk_overlap_input",
            on_change=update_chunk_overlap_slider,
        )
        embed_request.chunk_overlap = math.ceil((chunk_overlap_pct / 100) * embed_request.chunk_size)

    col2_1, col2_2 = st.columns([0.5, 0.5])
    embed_request.distance_metric = col2_1.selectbox(
        "Distance Metric:",
        list(DistanceMetrics.__args__),
        key="selected_distance_metric",
        help=help_text.help_dict["distance_metric"],
    )
    embed_request.index_type = col2_2.selectbox(
        "Index Type:", list(IndexTypes.__args__), key="selected_index_type", help=help_text.help_dict["index_type"]
    )


def _render_file_source_section(file_sources: list, oci_setup: dict) -> tuple:
    """Render file source selection and return processing data"""
    st.header("Load Knowledge Base", divider="red")
    file_source = st.radio("Knowledge Base Source:", file_sources, key="radio_file_source", horizontal=True)
    button_help = None
    populate_button_disabled = True
    web_url = None
    src_bucket = None
    src_files_selected = None
    db_connection = None
    sql_query = None

    ######################################
    # SQL Source
    ######################################
    if file_source == "SQL":
        button_help = """
            This button is disabled if there the SQL was unable to be validated.  Please check the SQL.
        """
        st.subheader("SQL query", divider=False)
        db_connection = st.text_input("DB Connection:", key="db_connection_url")
        sql_query = st.text_input("SQL:", key="sql_query")

        populate_button_disabled, msg = functions.is_sql_accessible(db_connection, sql_query)
        if not populate_button_disabled or msg != "":
            st.error(f"Error: {msg}")

    ######################################
    # Local Source
    ######################################
    if file_source == "Local":
        button_help = "This button is disabled if no local files have been provided."
        st.subheader("Local Files", divider=False)
        embed_files = st.file_uploader(
            "Choose a file:",
            key="local_file_uploader",
            help="Large or many files?  Consider OCI Object Storage or invoking the API directly.",
            accept_multiple_files=True,
        )
        populate_button_disabled = len(embed_files) == 0

    elif file_source == "Web":
        button_help = "This button is disabled if there the URL was unable to be validated.  Please check the URL."
        st.subheader("Web Pages", divider=False)
        web_url = st.text_input("URL:", key="selected_web_url")
        is_web_accessible, _ = functions.is_url_accessible(web_url)
        populate_button_disabled = not (web_url and is_web_accessible)

    elif file_source == "OCI":
        button_help = """This button is disabled if there are no documents from the source bucket split with
            the current split and embed options.  Please Split and Embed to enable Vector Storage."""
        st.text(f"OCI namespace: {oci_setup['namespace']}")
        oci_compartments = get_compartments()
        src_bucket_list = []
        col2_1, col2_2 = st.columns([0.5, 0.5])
        with col2_1:
            bucket_compartment = st.selectbox(
                "Bucket compartment:",
                list(oci_compartments.keys()),
                index=None,
                placeholder="Select bucket compartment...",
            )
            if bucket_compartment:
                src_bucket_list = get_buckets(oci_compartments[bucket_compartment])
        with col2_2:
            src_bucket = st.selectbox(
                "Source bucket:",
                src_bucket_list,
                index=None,
                placeholder="Select source bucket...",
                disabled=not bucket_compartment,
            )
        if src_bucket:
            src_objects = get_bucket_objects(src_bucket)
            src_files = files_data_frame(src_objects)
        else:
            src_files = pd.DataFrame({"File": [], "Process": []})

        src_files_selected = files_data_editor(src_files, "source")
        populate_button_disabled = src_files_selected["Process"].sum() == 0

    return (
        file_source,
        populate_button_disabled,
        button_help,
        web_url,
        src_bucket,
        src_files_selected,
        db_connection,
        sql_query,
    )


def _render_vector_store_section(embed_request: DatabaseVectorStorage) -> tuple:
    """Render vector store configuration section and return validation status and rate limit"""
    st.header("Populate Vector Store", divider="red")
    database_lookup = st_common.state_configs_lookup("database_configs", "name")
    existing_vs = database_lookup.get(state.client_settings.get("database", {}).get("alias"), {}).get(
        "vector_stores", []
    )

    embed_alias_size, _ = st.columns([0.5, 0.5])
    embed_alias_invalid = False
    embed_request.vector_store = None

    # Create dropdown options from existing vector stores
    existing_vs_names = [vs.get("alias", "") for vs in existing_vs if vs.get("alias")]
    vs_options = ["Create new..."] + existing_vs_names

    with embed_alias_size:
        # Dropdown for existing vector stores
        selected_vs = st.selectbox(
            "Select or Create Vector Store:",
            options=vs_options,
            index=0,
            help="Select an existing vector store or create a new one",
            key="selected_vs_dropdown"
        )

        # Show text input if "Create new..." is selected or for editing
        if selected_vs == "Create new...":
            embed_request.alias = st.text_input(
                "New Vector Store Alias:",
                max_chars=20,
                help=help_text.help_dict["embed_alias"],
                key="selected_embed_alias",
                placeholder="Press Enter to set.",
            )
        else:
            # Use the selected existing vector store name
            embed_request.alias = selected_vs
            st.text_input(
                "Vector Store Alias:",
                value=selected_vs,
                max_chars=20,
                help=help_text.help_dict["embed_alias"],
                key="selected_embed_alias",
                disabled=True,
            )
    pattern = r"^[A-Za-z][A-Za-z0-9_]*$"
    if embed_request.alias and not re.match(pattern, embed_request.alias):
        st.error(
            "Invalid Alias! It must start with a letter and only contain alphanumeric characters and underscores."
        )
        embed_alias_invalid = True

    if not embed_alias_invalid:
        embed_request.vector_store, _ = functions.get_vs_table(
            **embed_request.model_dump(exclude={"database", "vector_store"})
        )
    vs_msg = f"{embed_request.vector_store}, will be created."
    if any(d.get("vector_store") == embed_request.vector_store for d in existing_vs):
        vs_msg = f"{embed_request.vector_store} exists, new chunks will be added."
    st.markdown(f"##### **Vector Store:** `{embed_request.vector_store}`")
    st.caption(f"{vs_msg}")

    # Always render rate limit input to ensure session state is initialized
    rate_size, _ = st.columns([0.28, 0.72])
    rate_limit = rate_size.number_input(
        "Rate Limit (RPM):",
        value=None,
        help="Leave blank for no rate-limiting - Requests Per Minute",
        max_value=60,
        key="selected_rate_limit",
    )

    return embed_alias_invalid, rate_limit, existing_vs


def _handle_vector_store_population(
    embed_request: DatabaseVectorStorage,
    file_source: str,
    populate_button_disabled: bool,
    button_help: str,
    web_url: str,
    src_bucket: str,
    src_files_selected,
    rate_limit: int,
    db_connection: str,
    sql_query: str,
    existing_vs: list,
) -> None:
    """Handle vector store population button and processing"""
    if not populate_button_disabled and embed_request.vector_store:
        if "button_populate" in state and state.button_populate is True:
            state.running = True
        else:
            state.running = False
    else:
        state.running = True
    if not embed_request.alias:
        st.info("Please provide a Vector Store Alias.")

    # Create two columns for buttons
    col_populate, col_refresh = st.columns([0.5, 0.5])

    with col_populate:
        populate_clicked = st.button(
            "Populate Vector Store",
            type="primary",
            key="button_populate",
            disabled=state.running,
            help=button_help,
        )

    with col_refresh:
        # Only show refresh button for OCI source and if vector store exists
        vs_exists = any(d.get("vector_store") == embed_request.vector_store for d in existing_vs)
        refresh_disabled = file_source != "OCI" or not vs_exists or state.running or not embed_request.alias
        refresh_help = "Refresh existing vector store with new/modified files from OCI bucket" if vs_exists else "Vector store must exist first"

        refresh_clicked = st.button(
            "Refresh from OCI",
            key="button_refresh",
            disabled=refresh_disabled,
            help=refresh_help,
        )

    if populate_clicked:
        try:
            with st.spinner("Populating Vector Store... please be patient.", show_time=True):
                endpoint = None
                api_payload = []
                if file_source == "Local":
                    endpoint = "v1/embed/local/store"
                    files = st_common.local_file_payload(state.local_file_uploader)
                    api_payload = {"files": files}

                if file_source == "Web":
                    endpoint = "v1/embed/web/store"
                    api_payload = {"json": [web_url]}

                if file_source == "SQL":
                    endpoint = "v1/embed/sql/store"
                    api_payload = {"json": [db_connection, sql_query]}

                if file_source == "OCI":
                    endpoint = f"v1/oci/objects/download/{src_bucket}/{state.client_settings['oci']['auth_profile']}"
                    process_list = src_files_selected[src_files_selected["Process"]].reset_index(drop=True)
                    api_payload = {"json": process_list["File"].tolist()}

                response = api_call.post(endpoint=endpoint, payload=api_payload)

                embed_params = {
                    "client": state.client_settings["client"],
                    "rate_limit": rate_limit,
                }
                response = api_call.post(
                    endpoint="v1/embed",
                    params=embed_params,
                    payload={"json": embed_request.model_dump()},
                    timeout=7200,
                )
            st.success(f"Vector Store Populated: {response['message']}", icon="✅")
            get_databases(force=True)
        except api_call.ApiError as ex:
            st.error(ex, icon="🚨")

    elif refresh_clicked:
        # Handle refresh button click
        state.running = True
        try:
            with st.spinner("Refreshing Vector Store... checking for new/modified files.", show_time=True):
                # Call the refresh endpoint
                refresh_request = {
                    "vector_store_alias": embed_request.alias,
                    "bucket_name": src_bucket,
                    "auth_profile": None,  # Set to None when using client header
                    "rate_limit": rate_limit if rate_limit else 0,
                }

                response = api_call.post(
                    endpoint="v1/embed/refresh",
                    params={"client": state.client_settings["client"]},
                    payload={"json": refresh_request},
                    timeout=7200,
                )

            # Display results
            if response.get("new_files", 0) > 0 or response.get("updated_files", 0) > 0:
                st.success(
                    f"✅ Refresh Complete!\n\n"
                    f"- New files: {response.get('new_files', 0)}\n"
                    f"- Updated files: {response.get('updated_files', 0)}\n"
                    f"- Chunks added: {response.get('total_chunks', 0)}\n"
                    f"- Total chunks in store: {response.get('total_chunks_in_store', 0)}",
                    icon="✅"
                )
            else:
                st.info(
                    f"No new or modified files found in the bucket.\n\n"
                    f"Total chunks in store: {response.get('total_chunks_in_store', 0)}",
                    icon="ℹ️"
                )

            get_databases(force=True)

        except api_call.ApiError as ex:
            st.error(f"Refresh failed: {ex}", icon="🚨")
        finally:
            state.running = False


#############################################################################
# MAIN
#############################################################################
def display_split_embed() -> None:
    """Streamlit GUI"""
    try:
        get_models()
        get_databases()
        get_oci()
    except api_call.ApiError:
        st.stop()

    db_avail = st_common.is_db_configured()
    if not db_avail:
        logger.debug("Embedding Disabled (Database not configured)")
        st.error("Database is not configured. Disabling Embedding.", icon="🛑")

    embed_models_enabled = st_common.enabled_models_lookup("embed")
    if not embed_models_enabled:
        logger.debug("Embedding Disabled (no Embedding Models)")
        st.error("No embedding models are configured and/or enabled. Disabling Embedding.", icon="🛑")

    if not db_avail or not embed_models_enabled:
        st.stop()

    file_sources = ["OCI", "Local", "Web", "SQL"]
    oci_lookup = st_common.state_configs_lookup("oci_configs", "auth_profile")
    oci_setup = oci_lookup.get(state.client_settings["oci"].get("auth_profile"))
    if not oci_setup or oci_setup.get("namespace") is None or oci_setup.get("tenancy") is None:
        st.warning("OCI is not fully configured, some functionality is disabled", icon="⚠️")
        file_sources.remove("OCI")

    embed_request = DatabaseVectorStorage()

    _render_embedding_configuration(embed_models_enabled, embed_request)

    (
        file_source,
        populate_button_disabled,
        button_help,
        web_url,
        src_bucket,
        src_files_selected,
        db_connection,
        sql_query,
    ) = _render_file_source_section(file_sources, oci_setup)

    embed_alias_invalid, rate_limit, existing_vs = _render_vector_store_section(embed_request)

    if not embed_alias_invalid:
        _handle_vector_store_population(
            embed_request,
            file_source,
            populate_button_disabled,
            button_help,
            web_url,
            src_bucket,
            src_files_selected,
            rate_limit,
            db_connection,
            sql_query,
            existing_vs,
        )


if __name__ == "__main__":
    display_split_embed()
