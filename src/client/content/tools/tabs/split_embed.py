"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes is used for the splitting and chunking process using Streamlit (`st`).
"""
# spell-checker:ignore selectbox hnsw ivf ocids iterrows isin

import math
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

import streamlit as st
from streamlit import session_state as state

from client.utils import api_call, st_common, vs_options

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
            return functions.is_sql_accessible(self.sql_connection, self.sql_query)[0]
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
    """Keep text and slider input aligned and ensure overlap doesn't exceed chunk size"""
    new_overlap = state.selected_chunk_overlap_input
    # Ensure overlap doesn't exceed chunk size
    if hasattr(state, "selected_chunk_size_slider"):
        chunk_size = state.selected_chunk_size_slider
        if new_overlap >= chunk_size:
            new_overlap = max(0, chunk_size - 1)
            state.selected_chunk_overlap_input = new_overlap
    state.selected_chunk_overlap_slider = new_overlap


def update_chunk_overlap_input() -> None:
    """Keep text and slider input aligned and ensure overlap doesn't exceed chunk size"""
    new_overlap = state.selected_chunk_overlap_slider
    # Ensure overlap doesn't exceed chunk size
    if hasattr(state, "selected_chunk_size_slider"):
        chunk_size = state.selected_chunk_size_slider
        if new_overlap >= chunk_size:
            new_overlap = max(0, chunk_size - 1)
            state.selected_chunk_overlap_slider = new_overlap
    state.selected_chunk_overlap_input = new_overlap


def update_chunk_size_slider() -> None:
    """Keep text and slider input aligned and adjust overlap if needed"""
    state.selected_chunk_size_slider = state.selected_chunk_size_input
    # If overlap exceeds new chunk size, cap it
    if hasattr(state, "selected_chunk_overlap_slider"):
        if state.selected_chunk_overlap_slider >= state.selected_chunk_size_slider:
            new_overlap = max(0, state.selected_chunk_size_slider - 1)
            state.selected_chunk_overlap_slider = new_overlap
            state.selected_chunk_overlap_input = new_overlap


def update_chunk_size_input() -> None:
    """Keep text and slider input aligned and adjust overlap if needed"""
    state.selected_chunk_size_input = state.selected_chunk_size_slider
    # If overlap exceeds new chunk size, cap it
    if hasattr(state, "selected_chunk_overlap_input"):
        if state.selected_chunk_overlap_input >= state.selected_chunk_size_input:
            new_overlap = max(0, state.selected_chunk_size_input - 1)
            state.selected_chunk_overlap_input = new_overlap
            state.selected_chunk_overlap_slider = new_overlap


#############################################################################
# Helper Functions
#############################################################################
def _render_embedding_config_section(embed_models_enabled: dict, embed_request: DatabaseVectorStorage) -> None:
    """Render the embedding configuration section

    Args:
        embed_models_enabled: Dictionary of enabled embedding models
        embed_request: The database vector storage request object
        show_vs_config: If True, show chunk size, overlap, distance metric, and index type options.
                       If False, these are determined by the selected existing vector store.
    """
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
            label="Chunk Size (tokens):",
            min_value=0,
            max_value=chunk_size_max,
            value=chunk_size_max,
            key="selected_chunk_size_slider",
            on_change=update_chunk_size_input,
            help=help_text.help_dict["chunk_size"],
        )
        st.slider(
            label="Chunk Overlap (% of Chunk Size)",
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
        # Labels are on purpose to avoid UI strangeness
        embed_request.chunk_size = st.number_input(
            label="_chunk_size",
            label_visibility="hidden",
            min_value=0,
            max_value=chunk_size_max,
            value=chunk_size_max,
            key="selected_chunk_size_input",
            on_change=update_chunk_size_slider,
        )
        chunk_overlap_pct = st.number_input(
            label="_chunk_overlap",
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


def _render_load_kb_section(file_sources: list, oci_setup: dict) -> FileSourceData:
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
        if not (is_invalid) or msg:
            st.error(f"Error: {msg}")

    ######################################
    # Local Source
    ######################################
    if data.file_source == "Local":
        st.subheader("Local Files", divider=False)
        st.file_uploader(
            "Choose files or a zip archive:",
            key="local_file_uploader",
            help="Upload individual files or a zip archive containing multiple documents. "
            "Large or many files? Consider OCI Object Storage.",
            type=["pdf","html","md","csv","txt","png","jpeg","zip"],
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
    total_files = file_list_response["total_files"]
    total_chunks = file_list_response["total_chunks"]
    expander_title = f"📁 Existing Embeddings ({total_files} files, {total_chunks} chunks)"
    orphaned = file_list_response.get("orphaned_chunks", 0)
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

        if file_list_response["total_files"] > 0:
            # Create DataFrame for better display
            files_df = pd.DataFrame(file_list_response["files"])

            # Select columns to display (always show filename and chunk_count)
            display_cols = ["filename", "chunk_count"]
            column_config = {
                "filename": st.column_config.TextColumn("File Name", width="medium"),
                "chunk_count": st.column_config.NumberColumn("Chunks", width="small"),
            }

            # Only include size column if at least one file has size data
            if "size" in files_df.columns and files_df["size"].notna().any():
                files_df["size"] = files_df["size"].apply(lambda x: f"{x / 1024:.1f} KB" if x else "N/A")
                display_cols.append("size")
                column_config["size"] = st.column_config.TextColumn("Size", width="small")

            # Only include time_modified column if at least one file has timestamp data
            if "time_modified" in files_df.columns and files_df["time_modified"].notna().any():
                files_df["time_modified"] = files_df["time_modified"].apply(lambda x: x.split("T")[0] if x else "N/A")
                display_cols.append("time_modified")
                column_config["time_modified"] = st.column_config.TextColumn("Modified", width="small")

            st.dataframe(files_df[display_cols], width="stretch", hide_index=True, column_config=column_config)
        else:
            st.info("No files found in this vector store.")


def _validate_new_alias(alias: str) -> bool:
    """Validate a new vector store alias and display appropriate messages."""
    alias_pattern = r"^[A-Za-z][A-Za-z0-9_]*$"
    if not alias:
        return True
    if not re.match(alias_pattern, alias):
        st.error(
            "Invalid Alias! It must start with a letter and only contain alphanumeric characters and underscores."
        )
        return True
    return False


def _render_populate_vs_section(
    embed_request: DatabaseVectorStorage, create_new_vs: bool
) -> tuple[DatabaseVectorStorage, int]:
    """Render vector store configuration section and return validation status and rate limit

    Args:
        embed_request: The database vector storage request object
        create_new_vs: If True, allow creating new vector store. If False, select from existing only.

    Returns:
        Tuple of (embed_alias_invalid, rate_limit, vs_table)
    """
    st.header("Populate Vector Store", divider="red")

    embed_request.vector_store = None
    embed_alias_invalid = False
    if not create_new_vs:
        # Using existing Vector Store
        vs_settings = state.client_settings["vector_search"]
        for field in ["alias", "description", "model", "chunk_size", "chunk_overlap", "distance_metric", "index_type"]:
            setattr(embed_request, field, vs_settings.get(field, ""))

    if create_new_vs:
        # Creating new vector store: just show text input for new VS name
        embed_request.alias = st.text_input(
            "Vector Store Alias:",
            max_chars=20,
            help=help_text.help_dict["embed_alias"],
            key="selected_embed_alias",
            placeholder="Enter a name for the new vector store",
        )
        embed_alias_invalid = _validate_new_alias(embed_request.alias)

    if not embed_alias_invalid and embed_request.alias:
        embed_request.vector_store, _ = functions.get_vs_table(
            **embed_request.model_dump(exclude={"database", "vector_store"})
        )

        # Show full vector store table name and check existence
        st.markdown(f"##### **Vector Store:** `{embed_request.vector_store}`")
        vs_exists = any(
            store["vector_store"] == embed_request.vector_store
            for db in state.database_configs
            for store in db.get("vector_stores", [])
        )
        if vs_exists:
            try:
                file_list_response = api_call.get(endpoint=f"v1/embed/{embed_request.vector_store}/files")
                if file_list_response and "files" in file_list_response:
                    _display_file_list_expander(file_list_response)
            except api_call.ApiError as e:
                logger.warning("Could not retrieve file list for %s: %s", embed_request.vector_store, e)
        else:
            st.caption("A new vector store will be created.")

    # Vector Store Description
    st.divider()
    col1, col2 = st.columns([4, 1])
    with col1:
        embed_request.description = st.text_input(
            "Provide a description to help AI understand this purpose of this Vector Store:",
            max_chars=255,
            value=embed_request.description,
            placeholder="Enter a description for the Vector Store.",
            # label_visibility="collapsed",
        )
    col2.space("small")
    with col2:
        if not create_new_vs:
            if st.button(
                "Update Description",
                type="secondary",
                key="comment_update",
                help="Update the description of the Vector Store.",
            ):
                _ = api_call.patch(
                    endpoint="v1/embed/comment", payload={"json": embed_request.model_dump()}, toast=True
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

    return embed_request, rate_limit


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


def _render_population_button(
    embed_request: DatabaseVectorStorage, source_data: FileSourceData, create_new_vs: bool
) -> tuple[bool, bool]:
    """Render the appropriate button and return click states"""
    is_source_valid = source_data.is_valid()

    if not embed_request.alias and create_new_vs:
        st.info("Please provide a Vector Store Alias.", icon="⚠️")

    refresh_clicked = False
    populate_clicked = False

    if source_data.file_source == "OCI" and not create_new_vs:
        state.running = (
            not (is_source_valid and embed_request.vector_store) and state.get("button_refresh") is not True
        )
        refresh_clicked = st.button(
            "Refresh from OCI",
            type="primary",
            key="button_refresh",
            disabled=state.running,
            help="Refresh vector store with new/modified files from OCI bucket",
        )
    else:
        state.running = (
            not (is_source_valid and embed_request.vector_store) and state.get("button_populate") is not True
        )
        populate_clicked = st.button(
            "Populate Vector Store",
            type="primary",
            key="button_populate",
            disabled=state.running,
            help=source_data.get_button_help(),
        )

    return populate_clicked, refresh_clicked


def _handle_populate_success(response: dict) -> None:
    """Handle successful population response display"""
    # Display success message
    st.success(f"{response.get('message', 'Vector store populated successfully')}", icon="✅")

    # Display processing summary
    total_chunks = response.get('total_chunks', 0)
    processed_files = response.get('processed_files', [])
    skipped_files = response.get('skipped_files', [])

    with st.expander("📊 Processing Summary", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Chunks", total_chunks)
        with col2:
            st.metric("Files Processed", len(processed_files))
        with col3:
            st.metric("Files Skipped", len(skipped_files))

        if processed_files:
            st.subheader("✅ Processed Files")
            processed_df = pd.DataFrame(processed_files)
            st.dataframe(processed_df, use_container_width=True, hide_index=True)

        if skipped_files:
            st.subheader("⚠️ Skipped Files")
            skipped_df = pd.DataFrame(skipped_files)
            st.dataframe(skipped_df, use_container_width=True, hide_index=True)

    get_databases(force=True)


def _handle_refresh_success(response: dict) -> None:
    """Handle successful refresh response display"""
    # Display results
    if response.get("new_files", 0) > 0 or response.get("updated_files", 0) > 0:
        st.success(
            f"Refresh Complete!\n\n"
            f"- New files: {response.get('new_files', 0)}\n"
            f"- Updated files: {response.get('updated_files', 0)}\n"
            f"- Chunks added: {response.get('total_chunks', 0)}\n"
            f"- Total chunks in store: {response.get('total_chunks_in_store', 0)}",
            icon="✅",
        )
    else:
        st.info(
            f"No new or modified files found in the bucket.\n\n"
            f"Total chunks in store: {response.get('total_chunks_in_store', 0)}",
            icon="ℹ️",
        )
    get_databases(force=True)


def _handle_vector_store_population(
    embed_request: DatabaseVectorStorage, source_data: FileSourceData, rate_limit: int, create_new_vs: bool
) -> None:
    """Handle vector store population button and processing"""
    populate_clicked, refresh_clicked = _render_population_button(embed_request, source_data, create_new_vs)

    if populate_clicked:
        try:
            with st.spinner("Populating Vector Store... please be patient.", show_time=True):
                response = _process_populate_request(embed_request, source_data, rate_limit)
            _handle_populate_success(response)
        except api_call.ApiError as ex:
            st.error(ex, icon="🚨")
    elif refresh_clicked:
        state.running = True
        try:
            with st.spinner("Refreshing Vector Store... checking for new/modified files.", show_time=True):
                response = _process_refresh_request(embed_request, source_data.oci_bucket, rate_limit)
            _handle_refresh_success(response)
        except api_call.ApiError as ex:
            st.error(f"Refresh failed: {ex}", icon="🚨")
        finally:
            state.running = False


def _initialize_and_validate_config() -> tuple[dict, list]:
    """Initialize configuration and validate prerequisites"""
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

    # Setup Corpus Sources
    file_sources = ["OCI", "Local", "Web", "SQL"]
    oci_lookup = st_common.state_configs_lookup("oci_configs", "auth_profile")
    oci_setup = oci_lookup.get(state.client_settings["oci"].get("auth_profile"))
    if not oci_setup or oci_setup.get("namespace") is None or oci_setup.get("tenancy") is None:
        st.warning("OCI is not fully configured, some functionality is disabled", icon="⚠️")
        file_sources.remove("OCI")

    return embed_models_enabled, file_sources, oci_setup


def _configure_vector_store_mode(embed_models_enabled: dict) -> tuple[bool, DatabaseVectorStorage]:
    """Configure vector store creation mode and return request object"""
    embed_request = DatabaseVectorStorage()

    # Check for existing Vector Stores with corresponding enabled embedding models
    create_new_vs = True

    db_alias = state.client_settings.get("database", {}).get("alias")
    database_lookup = st_common.state_configs_lookup("database_configs", "name")
    vs_df = pd.DataFrame(database_lookup.get(db_alias, {}).get("vector_stores", []))
    # Remove VS if its embedding model does not exist/is disabled
    vs_filtered = vs_df[vs_df["model"].isin(embed_models_enabled.keys())] if not vs_df.empty else vs_df

    if not vs_filtered.empty:
        # Toggle between creating new vector store or using existing
        create_new_vs = st.toggle(
            "Create New Vector Store",
            key="selected_create_new_vs",
            value=True,
            help="Toggle between creating a new vector store or adding to an existing one. "
            "When using an existing vector store, chunk size, overlap, distance metric, "
            "and index type are already defined and cannot be changed.",
        )
        if not create_new_vs:
            # Render vector store selection controls
            vs_options.vector_store_selection(location="main")

    # Render embedding configuration for new VS
    if create_new_vs:
        _render_embedding_config_section(embed_models_enabled, embed_request)
    else:
        vs_settings = state.client_settings.get("vector_search", {})
        vs_fields = ["alias", "model", "chunk_size", "chunk_overlap", "distance_metric", "index_type"]
        vs_missing = [field for field in vs_fields if not vs_settings.get(field)]
        if vs_missing:
            st.stop()

    return create_new_vs, embed_request


#############################################################################
# MAIN
#############################################################################
def display_split_embed() -> None:
    """Streamlit GUI"""
    embed_models_enabled, file_sources, oci_setup = _initialize_and_validate_config()

    create_new_vs, embed_request = _configure_vector_store_mode(embed_models_enabled)

    source_data = _render_load_kb_section(file_sources, oci_setup)

    embed_request, rate_limit = _render_populate_vs_section(embed_request, create_new_vs)

    if embed_request:
        _handle_vector_store_population(embed_request, source_data, rate_limit, create_new_vs)


if __name__ == "__main__":
    display_split_embed()
