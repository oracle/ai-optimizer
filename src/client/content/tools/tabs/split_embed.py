"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes is used for the splitting and chunking process using Streamlit (`st`).
"""
# spell-checker:ignore selectbox hnsw ivf ocids iterrows

import math
import re
from dataclasses import dataclass
from typing import Optional

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
# Classes
#####################################################
@dataclass
class FileSourceData:
    """Data class to hold file source configuration and validation state"""
    file_source: Optional[str] = None
    # Web source
    web_url: Optional[str] = None
    # OCI source
    oci_bucket: Optional[str] = None
    oci_files_selected: Optional[pd.DataFrame] = None
    # SQL source
    sql_connection: Optional[str] = None
    sql_query: Optional[str] = None

    def is_valid(self) -> bool:
        """Check if the current file source configuration is valid"""
        if self.file_source == "Local":
            return bool(state.get("local_file_uploader"))
        if self.file_source == "Web":
            return bool(self.web_url and functions.is_url_accessible(self.web_url)[0])
        if self.file_source == "SQL":
            return not functions.is_sql_accessible(self.sql_connection, self.sql_query)[0]
        if self.file_source == "OCI":
            return bool(self.oci_files_selected is not None and self.oci_files_selected["Process"].sum() > 0)
        return False

    def get_button_help(self) -> str:
        """Get help text for the populate button based on file source"""
        help_text_map = {
            "Local": "This button is disabled if no local files have been provided.",
            "Web": "This button is disabled if there the URL was unable to be validated.  Please check the URL.",
            "SQL": "This button is disabled if there the SQL was unable to be validated.  Please check the SQL.",
            "OCI": "This button is disabled if there are no documents from the source bucket split with "
                   "the current split and embed options.  Please Split and Embed to enable Vector Storage.",
        }
        return help_text_map.get(self.file_source, "")

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
    if not objects:
        return pd.DataFrame({"File": [], "Process": []})
    return pd.DataFrame({"File": objects, "Process": [process] * len(objects)})


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

def _render_file_source_section(file_sources: list, oci_setup: dict) -> FileSourceData:
    """Render file source selection and return processing data"""
    st.header("Load Knowledge Base", divider="red")
    data = FileSourceData()
    data.file_source = st.radio("Knowledge Base Source:", file_sources, key="radio_file_source", horizontal=True)

    ######################################
    # SQL Source
    ######################################
    if data.file_source == "SQL":
        st.subheader("SQL query", divider=False)
        data.sql_connection = st.text_input("DB Connection:", key="db_connection_url")
        data.sql_query = st.text_input("SQL:", key="sql_query")

        is_invalid, msg = functions.is_sql_accessible(data.sql_connection, data.sql_query)
        if is_invalid or msg:
            st.error(f"Error: {msg}")

    ######################################
    # Local Source
    ######################################
    if data.file_source == "Local":
        st.subheader("Local Files", divider=False)
        st.file_uploader(
            "Choose a file:",
            key="local_file_uploader",
            help="Large or many files?  Consider OCI Object Storage or invoking the API directly.",
            accept_multiple_files=True,
        )

    elif data.file_source == "Web":
        st.subheader("Web Pages", divider=False)
        data.web_url = st.text_input("URL:", key="selected_web_url")

    elif data.file_source == "OCI":
        st.text(f"OCI namespace: {oci_setup['namespace']}")
        oci_compartments = get_compartments()
        col2_1, col2_2 = st.columns([0.5, 0.5])
        with col2_1:
            bucket_compartment = st.selectbox(
                "Bucket compartment:",
                list(oci_compartments.keys()),
                index=None,
                placeholder="Select bucket compartment...",
            )
            src_bucket_list = get_buckets(oci_compartments[bucket_compartment]) if bucket_compartment else []
        with col2_2:
            data.oci_bucket = st.selectbox(
                "Source bucket:",
                src_bucket_list,
                index=None,
                placeholder="Select source bucket...",
                disabled=not bucket_compartment,
            )

        src_objects = get_bucket_objects(data.oci_bucket) if data.oci_bucket else []
        src_files = files_data_frame(src_objects)
        data.oci_files_selected = files_data_editor(src_files, "source")

    return data


def _display_file_list_expander(file_list_response: dict) -> None:
    """Display the file list expander with embedded files information"""
    # Build expander title
    total_files = file_list_response['total_files']
    total_chunks = file_list_response['total_chunks']
    expander_title = f"📁 View Embedded Files ({total_files} files, {total_chunks} chunks)"
    orphaned = file_list_response.get('orphaned_chunks', 0)
    if orphaned > 0:
        expander_title += f" ⚠️ {orphaned} orphaned"

    with st.expander(expander_title):
        # Add refresh button
        _, col2 = st.columns([0.9, 0.1])
        with col2:
            if st.button("🔄", key="refresh_file_list", help="Refresh file list"):
                st.rerun()

        # Show warning if there are orphaned chunks
        if orphaned > 0:
            st.warning(
                f"**{orphaned} orphaned chunks found** - "
                "These chunks have missing or invalid filename metadata "
                "and won't be shown in search results properly."
            )

        if file_list_response['total_files'] > 0:
            # Create DataFrame for better display
            files_df = pd.DataFrame(file_list_response['files'])

            # Select columns to display (always show filename and chunk_count)
            display_cols = ['filename', 'chunk_count']
            column_config = {
                "filename": st.column_config.TextColumn("File Name", width="medium"),
                "chunk_count": st.column_config.NumberColumn("Chunks", width="small"),
            }

            # Only include size column if at least one file has size data
            if 'size' in files_df.columns and files_df['size'].notna().any():
                files_df['size'] = files_df['size'].apply(
                    lambda x: f"{x / 1024:.1f} KB" if x else "N/A"
                )
                display_cols.append('size')
                column_config["size"] = st.column_config.TextColumn("Size", width="small")

            # Only include time_modified column if at least one file has timestamp data
            if 'time_modified' in files_df.columns and files_df['time_modified'].notna().any():
                files_df['time_modified'] = files_df['time_modified'].apply(
                    lambda x: x.split('T')[0] if x else "N/A"
                )
                display_cols.append('time_modified')
                column_config["time_modified"] = st.column_config.TextColumn("Modified", width="small")

            st.dataframe(
                files_df[display_cols],
                use_container_width=True,
                hide_index=True,
                column_config=column_config
            )
        else:
            st.info("No files found in this vector store.")


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

    # Filter vector stores by matching chunk size and overlap
    matching_vs = [
        vs for vs in existing_vs
        if vs.get("chunk_size") == embed_request.chunk_size
        and vs.get("chunk_overlap") == embed_request.chunk_overlap
        and vs.get("alias")
    ]
    matching_vs_names = [vs.get("alias", "") for vs in matching_vs]
    vs_options = ["Create new..."] + matching_vs_names

    with embed_alias_size:
        # Dropdown for existing vector stores
        selected_vs = st.selectbox(
            "Select or Create Vector Store:",
            options=vs_options,
            index=0,
            help="Only showing vector stores with matching chunk size and overlap configuration",
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

    # Check if alias is empty when creating new vector store
    if selected_vs == "Create new..." and not embed_request.alias:
        st.warning("Please enter a Vector Store Alias to continue.")
        embed_alias_invalid = True
    elif embed_request.alias and not re.match(pattern, embed_request.alias):
        st.error(
            "Invalid Alias! It must start with a letter and only contain alphanumeric characters and underscores."
        )
        embed_alias_invalid = True

    if not embed_alias_invalid:
        embed_request.vector_store, _ = functions.get_vs_table(
            **embed_request.model_dump(exclude={"database", "vector_store"})
        )
        vs_msg = f"{embed_request.vector_store}, will be created."
        vs_exists = any(d.get("vector_store") == embed_request.vector_store for d in existing_vs)
        if vs_exists:
            vs_msg = f"{embed_request.vector_store} exists, new chunks will be added."
        st.markdown(f"##### **Vector Store:** `{embed_request.vector_store}`")
        st.caption(f"{vs_msg}")

        # Display files in existing vector store
        if vs_exists and embed_request.vector_store:
            try:
                file_list_response = api_call.get(
                    endpoint=f"v1/embed/{embed_request.vector_store}/files"
                )
                if file_list_response and "files" in file_list_response:
                    _display_file_list_expander(file_list_response)
            except api_call.ApiError as e:
                logger.warning(
                    "Could not retrieve file list for %s: %s", embed_request.vector_store, e
                )

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


def _process_populate_request(
    embed_request: DatabaseVectorStorage,
    source_data: FileSourceData,
    rate_limit: int,
) -> dict:
    """Process the populate vector store request"""
    if source_data.file_source == "Local":
        endpoint = "v1/embed/local/store"
        files = st_common.local_file_payload(state.local_file_uploader)
        api_payload = {"files": files}
    elif source_data.file_source == "Web":
        endpoint = "v1/embed/web/store"
        api_payload = {"json": [source_data.web_url]}
    elif source_data.file_source == "SQL":
        endpoint = "v1/embed/sql/store"
        api_payload = {"json": [source_data.sql_connection, source_data.sql_query]}
    else:  # OCI
        endpoint = f"v1/oci/objects/download/{source_data.oci_bucket}/{state.client_settings['oci']['auth_profile']}"
        process_list = source_data.oci_files_selected[source_data.oci_files_selected["Process"]].reset_index(drop=True)
        api_payload = {"json": process_list["File"].tolist()}

    api_call.post(endpoint=endpoint, payload=api_payload)

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
    return response


def _process_refresh_request(embed_request: DatabaseVectorStorage, src_bucket: str, rate_limit: int) -> dict:
    """Process the refresh vector store request"""
    refresh_request = {
        "vector_store_alias": embed_request.alias,
        "bucket_name": src_bucket,
        "auth_profile": None,
        "rate_limit": rate_limit if rate_limit else 0,
    }

    response = api_call.post(
        endpoint="v1/embed/refresh",
        params={"client": state.client_settings["client"]},
        payload={"json": refresh_request},
        timeout=7200,
    )
    return response


def _handle_vector_store_population(
    embed_request: DatabaseVectorStorage,
    source_data: FileSourceData,
    rate_limit: int,
    existing_vs: list,
) -> None:
    """Handle vector store population button and processing"""
    is_source_valid = source_data.is_valid()
    state.running = not (is_source_valid and embed_request.vector_store) or state.get("button_populate") is True

    if not embed_request.alias:
        st.info("Please provide a Vector Store Alias.")

    # Create two columns for buttons
    col_populate, col_refresh = st.columns([0.5, 0.5])

    # Check if vector store exists
    vs_exists = any(d.get("vector_store") == embed_request.vector_store for d in existing_vs)

    with col_populate:
        populate_clicked = st.button(
            "Populate Vector Store",
            type="primary",
            key="button_populate",
            disabled=state.running,
            help=source_data.get_button_help(),
        )

    with col_refresh:
        refresh_disabled = (
            source_data.file_source != "OCI" or not vs_exists or state.running or not embed_request.alias
        )
        refresh_help = (
            "Refresh existing vector store with new/modified files from OCI bucket"
            if vs_exists else "Vector store must exist first"
        )
        refresh_clicked = st.button(
            "Refresh from OCI",
            key="button_refresh",
            disabled=refresh_disabled,
            help=refresh_help,
        )

    if populate_clicked:
        try:
            with st.spinner("Populating Vector Store... please be patient.", show_time=True):
                response = _process_populate_request(embed_request, source_data, rate_limit)
            st.success(f"Vector Store Populated: {response['message']}", icon="✅")
            get_databases(force=True)
        except api_call.ApiError as ex:
            st.error(ex, icon="🚨")

    elif refresh_clicked:
        state.running = True
        try:
            with st.spinner("Refreshing Vector Store... checking for new/modified files.", show_time=True):
                response = _process_refresh_request(embed_request, source_data.oci_bucket, rate_limit)

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

    source_data = _render_file_source_section(file_sources, oci_setup)

    embed_alias_invalid, rate_limit, existing_vs = _render_vector_store_section(embed_request)

    if not embed_alias_invalid:
        _handle_vector_store_population(
            embed_request,
            source_data,
            rate_limit,
            existing_vs,
        )


if __name__ == "__main__":
    display_split_embed()
