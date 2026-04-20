"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Split and Embed tab — document splitting, chunking, embedding, and vector store population.
"""
# spell-checker:ignore selectbox hnsw ivf iterrows isin ocid

import logging
import math
import re
from dataclasses import dataclass
from typing import Optional

import httpx
import pandas as pd
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import api_get, api_patch, api_post
from client.app.core.sidebar import vector_store_selection

LOGGER = logging.getLogger("client.content.tools.tabs.split_embed")

DISTANCE_STRATEGIES = ["COSINE", "DOT_PRODUCT", "EUCLIDEAN_DISTANCE"]
INDEX_TYPES = ["HNSW", "IVF", "HYB"]


#####################################################
# Inline Utilities
#####################################################
@st.cache_data(ttl=30, show_spinner=False)
def _is_url_accessible(url: str) -> tuple[bool, str]:
    """Check if a URL is reachable."""
    if not url:
        return False, "No URL Provided"
    try:
        with httpx.Client(timeout=2, follow_redirects=True) as client:
            response = client.get(url)
        if response.status_code in {200, 401, 403, 404, 421}:
            return True, ""
        msg = f"{url} is not accessible. (Status: {response.status_code})"
        return False, msg
    except httpx.HTTPError as ex:
        msg = f"{url} is not accessible. ({type(ex).__name__})"
        return False, msg


def _generate_vs_table_name(
    alias: str,
    model_key: str,
    chunk_size: int,
    chunk_overlap: int,
    distance_strategy: str,
    index_type: str = "HNSW",
) -> str | None:
    """Generate a preview vector store table name (for UI display only)."""
    try:
        overlap_ceil = math.ceil(chunk_overlap)
        table_string = f"{model_key}_{chunk_size}_{overlap_ceil}_{distance_strategy}_{index_type}"
        if alias:
            table_string = f"{alias}_{table_string}"
        return re.sub(r"\W", "_", table_string.upper())
    except TypeError:
        return None


def _validate_new_alias(alias: str) -> bool:
    """Validate alias; returns True if there are errors to show."""
    if not alias:
        return True
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", alias):
        st.error("Invalid Alias! It must start with a letter and only contain alphanumeric characters and underscores.")
        return True
    return False


def _build_embed_payload(embed_config: dict) -> dict:
    """Build the server-compatible payload from embed config."""
    model_key = embed_config.get("model_key", "")
    parts = model_key.split("/", 1) if model_key else []
    embedding_model = {"provider": parts[0], "id": parts[1]} if len(parts) == 2 else None

    return helpers.build_payload(
        {
            "alias": embed_config.get("alias"),
            "description": embed_config.get("description"),
            "embedding_model": embedding_model,
            "chunk_size": embed_config.get("chunk_size"),
            "chunk_overlap": embed_config.get("chunk_overlap"),
            "distance_strategy": embed_config.get("distance_strategy"),
            "index_type": embed_config.get("index_type"),
            "parsing_mode": embed_config.get("parsing_mode", "fast"),
        }
    )


#####################################################
# Classes
#####################################################
@dataclass
class FileSourceData:
    """Data class to hold file source configuration and validation state."""

    file_source: Optional[str] = None
    web_url: Optional[str] = None
    oci_bucket: Optional[str] = None
    oci_files_selected: Optional[pd.DataFrame] = None
    sql_query: Optional[str] = None
    sql_db_alias: Optional[str] = None

    def is_valid(self) -> bool:
        """Check if the current file source configuration is valid."""
        if self.file_source == "Local":
            return bool(state.get("runtime_local_file_uploader"))
        if self.file_source == "Web":
            return bool(self.web_url and _is_url_accessible(self.web_url)[0])
        if self.file_source == "SQL":
            return bool(self.sql_query and self.sql_query.strip() and self.sql_db_alias)
        if self.file_source == "OCI":
            return bool(self.oci_files_selected is not None and self.oci_files_selected["Process"].sum() > 0)
        return False

    def get_button_help(self) -> str:
        """Get help text for the populate button based on file source."""
        help_map = {
            "Local": "This button is disabled if no local files have been provided.",
            "Web": "This button is disabled if the URL was unable to be validated. Please check the URL.",
            "SQL": "This button is disabled if no SQL query was provided or no database is selected.",
            "OCI": "This button is disabled if there are no documents from the source bucket selected for processing.",
        }
        return help_map.get(self.file_source or "", "")


#####################################################
# OCI Caching Functions
#####################################################
@st.cache_data(show_spinner="Retrieving OCI Compartments")
def _get_compartments(auth_profile: str) -> dict:
    """Get OCI compartments via server endpoint."""
    try:
        return api_get(f"oci/compartments/{auth_profile}")
    except httpx.HTTPStatusError:
        return {}


def _get_buckets(compartment_ocid: str, auth_profile: str) -> list:
    """Get OCI bucket names in a compartment."""
    try:
        return api_get(f"oci/buckets/{compartment_ocid}/{auth_profile}")
    except httpx.HTTPStatusError:
        return ["No Access to Buckets in this Compartment"]


def _get_bucket_objects(bucket_name: str, auth_profile: str) -> list:
    """Get object names from an OCI bucket."""
    return api_get(f"oci/objects/{bucket_name}/{auth_profile}")


@st.cache_resource
def _files_data_frame(objects, process=False):
    """Produce a data frame of files."""
    if not objects:
        return pd.DataFrame({"File": pd.Series([], dtype="str"), "Process": pd.Series([], dtype="bool")})
    return pd.DataFrame({"File": objects, "Process": [process] * len(objects)})


def _files_data_editor(files, key):
    """Render a data editor for file selection."""
    return st.data_editor(
        files,
        key=key,
        width="stretch",
        column_config={
            "Process": st.column_config.CheckboxColumn(
                "in",
                help="Select files **to include** into loading process",
                default=False,
            )
        },
        disabled=["File"],
        hide_index=True,
    )


#####################################################
# Chunk Size/Overlap Callbacks
#####################################################
def _update_chunk_overlap_slider() -> None:
    """Keep text and slider input aligned; ensure overlap doesn't exceed chunk size."""
    new_overlap = state.selected_chunk_overlap_input
    if hasattr(state, "selected_chunk_size_slider"):
        chunk_size = state.selected_chunk_size_slider
        overlap_tokens = math.ceil((new_overlap / 100) * chunk_size) if chunk_size else 0
        if chunk_size and overlap_tokens >= chunk_size:
            new_overlap = math.floor(((chunk_size - 1) / chunk_size) * 100)
            state.selected_chunk_overlap_input = new_overlap
    state.selected_chunk_overlap_slider = new_overlap


def _update_chunk_overlap_input() -> None:
    """Keep text and slider input aligned; ensure overlap doesn't exceed chunk size."""
    new_overlap = state.selected_chunk_overlap_slider
    if hasattr(state, "selected_chunk_size_slider"):
        chunk_size = state.selected_chunk_size_slider
        overlap_tokens = math.ceil((new_overlap / 100) * chunk_size) if chunk_size else 0
        if chunk_size and overlap_tokens >= chunk_size:
            new_overlap = math.floor(((chunk_size - 1) / chunk_size) * 100)
            state.selected_chunk_overlap_slider = new_overlap
    state.selected_chunk_overlap_input = new_overlap


def _update_chunk_size_slider() -> None:
    """Keep text and slider input aligned; adjust overlap if needed."""
    state.selected_chunk_size_slider = state.selected_chunk_size_input
    if hasattr(state, "selected_chunk_overlap_slider"):
        chunk_size = state.selected_chunk_size_slider
        overlap_pct = state.selected_chunk_overlap_slider
        overlap_tokens = math.ceil((overlap_pct / 100) * chunk_size) if chunk_size else 0
        if chunk_size and overlap_tokens >= chunk_size:
            new_overlap = math.floor(((chunk_size - 1) / chunk_size) * 100)
            state.selected_chunk_overlap_slider = new_overlap
            state.selected_chunk_overlap_input = new_overlap


def _update_chunk_size_input() -> None:
    """Keep text and slider input aligned; adjust overlap if needed."""
    state.selected_chunk_size_input = state.selected_chunk_size_slider
    if hasattr(state, "selected_chunk_overlap_input"):
        chunk_size = state.selected_chunk_size_input
        overlap_pct = state.selected_chunk_overlap_input
        overlap_tokens = math.ceil((overlap_pct / 100) * chunk_size) if chunk_size else 0
        if chunk_size and overlap_tokens >= chunk_size:
            new_overlap = math.floor(((chunk_size - 1) / chunk_size) * 100)
            state.selected_chunk_overlap_input = new_overlap
            state.selected_chunk_overlap_slider = new_overlap


#############################################################################
# UI Sections
#############################################################################
def _render_embedding_config_section(embed_models_enabled: dict, embed_config: dict) -> None:
    """Render the embedding configuration section and populate embed_config."""
    st.header("Embedding Configuration", divider="red")
    embed_config["model_key"] = st.selectbox(
        "Embedding models available: ",
        options=list(embed_models_enabled.keys()),
        index=0,
        key="selected_embed_model",
    )
    embed_url = embed_models_enabled[embed_config["model_key"]].get("api_base")
    if embed_url:
        st.write(f"Embedding Server: {embed_url}")
        is_accessible, err_msg = _is_url_accessible(embed_url)
        if not is_accessible:
            st.warning(err_msg, icon="⚠️")
            if st.button("Retry"):
                st.rerun()
            st.stop()

    chunk_size_max = embed_models_enabled[embed_config["model_key"]].get("max_chunk_size", 8192)
    # Clamp cached values when the model's max shrinks
    for key in ("selected_chunk_size_slider", "selected_chunk_size_input"):
        if key in state and state[key] > chunk_size_max:
            state[key] = chunk_size_max
    col1_1, col1_2 = st.columns([0.8, 0.2])
    with col1_1:
        st.slider(
            label="Chunk Size (tokens):",
            min_value=1,
            max_value=chunk_size_max,
            value=chunk_size_max,
            key="selected_chunk_size_slider",
            on_change=_update_chunk_size_input,
            help=state.optimizer_help.get("chunk_size", ""),
        )
        st.slider(
            label="Chunk Overlap (% of Chunk Size)",
            min_value=0,
            max_value=100,
            value=20,
            step=5,
            key="selected_chunk_overlap_slider",
            on_change=_update_chunk_overlap_input,
            format="%d%%",
            help=state.optimizer_help.get("chunk_overlap", ""),
        )

    with col1_2:
        embed_config["chunk_size"] = st.number_input(
            label="_chunk_size",
            label_visibility="hidden",
            min_value=1,
            max_value=chunk_size_max,
            value=chunk_size_max,
            key="selected_chunk_size_input",
            on_change=_update_chunk_size_slider,
        )
        chunk_overlap_pct = st.number_input(
            label="_chunk_overlap",
            label_visibility="hidden",
            min_value=0,
            max_value=100,
            value=20,
            step=5,
            key="selected_chunk_overlap_input",
            on_change=_update_chunk_overlap_slider,
        )
        embed_config["chunk_overlap"] = math.ceil((chunk_overlap_pct / 100) * embed_config["chunk_size"])

    col2_1, col2_2 = st.columns([0.5, 0.5])
    embed_config["distance_strategy"] = col2_1.selectbox(
        "Distance Strategy:",
        DISTANCE_STRATEGIES,
        key="selected_distance_strategy",
        help=state.optimizer_help.get("distance_metric", ""),
    )
    embed_config["index_type"] = col2_2.selectbox(
        "Index Type:",
        INDEX_TYPES,
        key="selected_index_type",
        help=state.optimizer_help.get("index_type", ""),
    )


def _render_load_kb_section(file_sources: list, oci_setup: dict | None) -> FileSourceData:
    """Render file source selection and return processing data."""
    st.header("Load Knowledge Base", divider="red")
    data = FileSourceData()
    data.file_source = st.radio("Knowledge Base Source:", file_sources, key="radio_file_source", horizontal=True)

    ######################################
    # SQL Source
    ######################################
    if data.file_source == "SQL":
        st.subheader("SQL query", divider=False)
        db_lookup = helpers.state_configs_lookup("database_configs", "alias")
        usable_aliases = [alias for alias, cfg in db_lookup.items() if cfg.get("usable")]
        current_alias = state["settings"]["client_settings"].get("database", {}).get("alias")
        default_index = usable_aliases.index(current_alias) if current_alias in usable_aliases else None
        data.sql_db_alias = st.selectbox(
            "Database:",
            usable_aliases,
            index=default_index,
            key="runtime_sql_db_alias",
            placeholder="Select database...",
            help="Select the database to execute the SQL query against.",
        )
        data.sql_query = st.text_input(
            "SQL:",
            key="runtime_sql_query",
            help="SQL query returning text data.",
        )
        if data.sql_query and not data.sql_query.strip():
            st.error("Please enter a valid SQL query.")

    ######################################
    # Local Source
    ######################################
    elif data.file_source == "Local":
        st.subheader("Local Files", divider=False)
        st.file_uploader(
            "Choose files or a zip archive:",
            key="runtime_local_file_uploader",
            help="Upload individual files or a zip archive containing multiple documents. "
            "Large or many files? Consider OCI Object Storage.",
            type=["pdf", "html", "md", "csv", "txt", "png", "jpg", "jpeg", "zip", "docx", "pptx", "xlsx"],
            accept_multiple_files=True,
        )

    ######################################
    # Web Source
    ######################################
    elif data.file_source == "Web":
        st.subheader("Web Pages", divider=False)
        data.web_url = st.text_input("URL:", key="runtime_web_url")

    ######################################
    # OCI Source
    ######################################
    elif data.file_source == "OCI" and oci_setup:
        auth_profile = state["settings"]["client_settings"].get("oci", {}).get("auth_profile", "")
        st.text(f"OCI namespace: {oci_setup.get('namespace', 'N/A')}")
        oci_compartments = _get_compartments(auth_profile)
        col2_1, col2_2 = st.columns([0.5, 0.5])
        with col2_1:
            bucket_compartment = st.selectbox(
                "Bucket compartment:",
                list(oci_compartments.keys()),
                index=None,
                placeholder="Select bucket compartment...",
            )
            src_bucket_list = (
                _get_buckets(oci_compartments[bucket_compartment], auth_profile) if bucket_compartment else []
            )
        with col2_2:
            data.oci_bucket = st.selectbox(
                "Source bucket:",
                src_bucket_list,
                index=None,
                placeholder="Select source bucket...",
                disabled=not bucket_compartment,
            )

        src_objects = _get_bucket_objects(data.oci_bucket, auth_profile) if data.oci_bucket else []
        src_files = _files_data_frame(src_objects)
        data.oci_files_selected = _files_data_editor(src_files, "source")

    return data


def _display_file_list_expander(file_list_response: dict) -> None:
    """Display the file list expander with embedded files information."""
    total_files = file_list_response["total_files"]
    total_chunks = file_list_response["total_chunks"]
    expander_title = f"Existing Embeddings ({total_files} files, {total_chunks} chunks)"
    orphaned = file_list_response.get("orphaned_chunks", 0)
    if orphaned > 0:
        expander_title += f" - {orphaned} orphaned"

    with st.expander(expander_title):
        _, col2 = st.columns([0.9, 0.1])
        with col2:
            if st.button("Refresh", key="refresh_file_list", help="Refresh file list"):
                st.rerun()

        if orphaned > 0:
            st.warning(
                f"**{orphaned} orphaned chunks found** - "
                "These chunks have missing or invalid filename metadata "
                "and won't be shown in search results properly."
            )

        if total_files > 0:
            files_df = pd.DataFrame(file_list_response["files"])
            display_cols = ["filename", "chunk_count"]
            column_config = {
                "filename": st.column_config.TextColumn("File Name", width="medium"),
                "chunk_count": st.column_config.NumberColumn("Chunks", width="small"),
            }

            if "size" in files_df.columns and files_df["size"].notna().any():
                files_df["size"] = files_df["size"].apply(lambda x: f"{x / 1024:.1f} KB" if x else "N/A")
                display_cols.append("size")
                column_config["size"] = st.column_config.TextColumn("Size", width="small")

            if "time_modified" in files_df.columns and files_df["time_modified"].notna().any():
                files_df["time_modified"] = files_df["time_modified"].apply(lambda x: x.split("T")[0] if x else "N/A")
                display_cols.append("time_modified")
                column_config["time_modified"] = st.column_config.TextColumn("Modified", width="small")

            st.dataframe(files_df[display_cols], width="stretch", hide_index=True, column_config=column_config)
        else:
            st.info("No files found in this vector store.")


def _render_populate_vs_section(embed_config: dict, create_new_vs: bool) -> int | None:
    """Render vector store configuration section.

    Mutates embed_config in-place to set alias, description, and vector_store.
    Returns the rate_limit value.
    """
    st.header("Populate Vector Store", divider="red")

    client_settings = state["settings"]["client_settings"]
    db_alias = client_settings.get("database", {}).get("alias")
    st.markdown(f"##### **Database:** `{db_alias}`")
    should_fetch_files = False
    vs_table = None

    if create_new_vs:
        embed_config["vector_store"] = None
        embed_config["alias"] = st.text_input(
            "Vector Store Alias:",
            max_chars=20,
            help=state.optimizer_help.get("embed_alias", ""),
            key="selected_embed_alias",
            placeholder="Enter a name for the new vector store",
        )
        if embed_config["alias"] and not _validate_new_alias(embed_config["alias"]):
            vs_table = _generate_vs_table_name(
                alias=embed_config["alias"],
                model_key=embed_config.get("model_key", ""),
                chunk_size=embed_config.get("chunk_size", 0),
                chunk_overlap=embed_config.get("chunk_overlap", 0),
                distance_strategy=embed_config.get("distance_strategy", "COSINE"),
                index_type=embed_config.get("index_type", "HNSW"),
            )
            embed_config["vector_store"] = vs_table
            should_fetch_files = bool(
                vs_table
                and any(
                    store.get("vector_store") == vs_table
                    for db in state["settings"]["database_configs"]
                    for store in db.get("vector_stores", [])
                )
            )
            if vs_table and not should_fetch_files:
                st.caption("A new vector store will be created.")
    else:
        vs_settings = client_settings.get("vector_search", {})
        embed_config.update(
            {
                "alias": vs_settings.get("alias", ""),
                "chunk_size": vs_settings.get("chunk_size", 0),
                "chunk_overlap": vs_settings.get("chunk_overlap", 0),
                "distance_strategy": vs_settings.get("distance_strategy", ""),
                "index_type": vs_settings.get("index_type", ""),
            }
        )
        embed_config["model_key"] = (
            f"{vs_settings.get('provider')}/{vs_settings.get('id')}"
            if vs_settings.get("provider") and vs_settings.get("id")
            else ""
        )
        vs_table = vs_settings.get("vector_store")
        embed_config["vector_store"] = vs_table
        embed_config["description"] = (
            next(
                (
                    store.get("description", "")
                    for store in helpers.state_configs_lookup("database_configs", "alias")
                    .get(db_alias, {})
                    .get("vector_stores", [])
                    if store.get("vector_store") == vs_table
                ),
                "",
            )
            or ""
        )
        should_fetch_files = bool(vs_table)

    if vs_table:
        st.markdown(f"##### **Vector Store:** `{vs_table}`")
        if should_fetch_files:
            try:
                file_list = api_get(
                    f"embed/{vs_table}/files",
                    extra_headers={"client": state.optimizer_client},
                )
                if file_list and "files" in file_list:
                    _display_file_list_expander(file_list)
            except httpx.HTTPError as e:
                LOGGER.warning("Could not retrieve file list for %s: %s", vs_table, e)

    # Vector Store Description
    col1, col2 = st.columns([4, 1])
    with col1:
        embed_config["description"] = st.text_input(
            "Provide a description to help AI understand the purpose of this Vector Store:",
            max_chars=255,
            value=embed_config.get("description", "") or "",
            placeholder="Enter a description for the Vector Store.",
        )
    with col2:
        st.space()
        if not create_new_vs and st.button(
            "Update Description",
            type="secondary",
            key="comment_update",
            help="Update the description of the Vector Store.",
        ):
            api_patch(
                "embed/comment",
                json={
                    **_build_embed_payload(embed_config),
                    "vector_store": embed_config.get("vector_store"),
                },
                extra_headers={"client": state.optimizer_client},
                toast="Description updated.",
            )

    # Rate limit
    rate_limit = st.columns([0.28, 0.72])[0].number_input(
        "Rate Limit (RPM):",
        value=0,
        help="0 for no rate-limiting - Requests Per Minute",
        max_value=60,
        key="selected_rate_limit",
    )

    return rate_limit


#############################################################################
# Processing
#############################################################################
def _process_populate_request(embed_config: dict, source_data: FileSourceData, rate_limit: int | None) -> dict:
    """Store source files then run split-and-embed."""
    client_header = {"client": state.optimizer_client}
    auth_profile = state["settings"]["client_settings"].get("oci", {}).get("auth_profile", "")

    # Step 1: Store source files on server
    if source_data.file_source == "Local":
        files = helpers.unique_file_payload(state.runtime_local_file_uploader)
        api_post("embed/local/store", files=files, extra_headers=client_header)
    elif source_data.file_source == "Web":
        api_post("embed/web/store", json=[source_data.web_url], extra_headers=client_header)
    elif source_data.file_source == "SQL":
        api_post(
            "embed/sql/store",
            json={"query": source_data.sql_query, "db_alias": source_data.sql_db_alias},
            extra_headers=client_header,
        )
    else:  # OCI
        oci_selected = source_data.oci_files_selected
        if oci_selected is None:
            return {}
        process_list = oci_selected[oci_selected["Process"]].reset_index(drop=True)
        file_names = process_list["File"].tolist()
        api_post(
            f"oci/objects/download/{source_data.oci_bucket or ''}/{auth_profile}",
            json=file_names,
            extra_headers=client_header,
        )

    # Step 2: Split and embed
    payload = _build_embed_payload(embed_config)
    response = api_post(
        "embed/",
        json=payload,
        params={"rate_limit": rate_limit or 0},
        extra_headers=client_header,
        timeout=7200,
    )
    return response


def _process_refresh_request(embed_config: dict, src_bucket: str, rate_limit: int | None) -> dict:
    """Refresh an existing vector store from an OCI bucket."""
    refresh_payload = {
        "vector_store_alias": embed_config.get("alias") or embed_config.get("vector_store", ""),
        "bucket_name": src_bucket,
        "auth_profile": state["settings"]["client_settings"].get("oci", {}).get("auth_profile", "DEFAULT"),
        "rate_limit": rate_limit or 0,
        "parsing_mode": embed_config.get("parsing_mode", "fast"),
    }
    response = api_post(
        "embed/refresh",
        json=refresh_payload,
        extra_headers={"client": state.optimizer_client},
        timeout=7200,
    )
    return response


def _render_population_button(
    embed_config: dict, source_data: FileSourceData, create_new_vs: bool
) -> tuple[bool, bool]:
    """Render the appropriate button and return click states."""
    is_source_valid = source_data.is_valid()

    if not embed_config.get("alias") and create_new_vs:
        st.info("Please provide a Vector Store Alias.", icon="⚠️")

    refresh_clicked = False
    populate_clicked = False

    col_btn, col_toggle = st.columns([3, 7])

    with col_toggle:
        deep_analysis = st.toggle(
            "Deep Analysis",
            value=False,
            key="selected_parsing_mode",
            width="stretch",
            help="""
                Enable for deep, thorough document analysis with better accuracy for complex layouts.
                Deep Analysis will take significantly longer to process the documents.
                """,
        )
    embed_config["parsing_mode"] = "deep" if deep_analysis else "fast"

    with col_btn:
        if source_data.file_source == "OCI" and not create_new_vs:
            is_refresh_ready = bool(source_data.oci_bucket) and bool(embed_config.get("vector_store"))
            state.running = not is_refresh_ready
            refresh_clicked = st.button(
                "Refresh from OCI",
                type="primary",
                icon="🔄",
                key="button_refresh",
                disabled=state.running,
                help="Refresh vector store with new/modified files from OCI bucket",
            )
        else:
            state.running = not (is_source_valid and embed_config.get("vector_store"))
            populate_clicked = st.button(
                "Populate Vector Store",
                type="primary",
                icon="📤",
                key="button_populate",
                disabled=state.running,
                help=source_data.get_button_help(),
            )

    return populate_clicked, refresh_clicked


def _handle_populate_success(response: dict) -> None:
    """Handle successful population response display."""
    st.success(f"{response.get('message', 'Vector store populated successfully')}", icon="✅")

    total_chunks = response.get("total_chunks", 0)
    processed_files = response.get("processed_files", [])
    skipped_files = response.get("skipped_files", [])

    with st.expander("Processing Summary", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Chunks", total_chunks)
        with col2:
            st.metric("Files Processed", len(processed_files))
        with col3:
            st.metric("Files Skipped", len(skipped_files))

        if processed_files:
            st.subheader("Processed Files")
            st.dataframe(pd.DataFrame(processed_files), width="stretch", hide_index=True)

        if skipped_files:
            st.subheader("Skipped Files")
            st.dataframe(pd.DataFrame(skipped_files), width="stretch", hide_index=True)

    helpers.refresh_settings()


def _handle_refresh_success(response: dict) -> None:
    """Handle successful refresh response display."""
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
    helpers.refresh_settings()


def _handle_vector_store_population(
    embed_config: dict, source_data: FileSourceData, rate_limit: int | None, create_new_vs: bool
) -> None:
    """Handle vector store population button and processing."""
    populate_clicked, refresh_clicked = _render_population_button(embed_config, source_data, create_new_vs)

    if populate_clicked:
        try:
            with st.spinner("Populating Vector Store... please be patient.", show_time=True):
                response = _process_populate_request(embed_config, source_data, rate_limit)
            _handle_populate_success(response)
        except httpx.HTTPStatusError as ex:
            st.error(helpers.extract_error_detail(ex), icon="🚨")
    elif refresh_clicked:
        state.running = True
        try:
            with st.spinner("Refreshing Vector Store... checking for new/modified files.", show_time=True):
                response = _process_refresh_request(embed_config, source_data.oci_bucket or "", rate_limit)
            _handle_refresh_success(response)
        except httpx.HTTPStatusError as ex:
            st.error(f"Refresh failed: {helpers.extract_error_detail(ex)}", icon="🚨")
        finally:
            state.running = False


#############################################################################
# Initialization
#############################################################################
def _is_db_configured() -> bool:
    """Check if a usable database is configured for the current client."""
    db_alias = state["settings"]["client_settings"].get("database", {}).get("alias")
    if not db_alias:
        return False
    db_lookup = helpers.state_configs_lookup("database_configs", "alias")
    db_config = db_lookup.get(db_alias)
    return bool(db_config and db_config.get("usable"))


def _initialize_and_validate_config() -> tuple[dict, list, dict | None]:
    """Initialize configuration and validate prerequisites."""
    if not _is_db_configured():
        LOGGER.debug("Embedding Disabled (Database not configured)")
        st.error("Database is not configured. Disabling Embedding.", icon="🛑")
        st.stop()

    embed_models_enabled = helpers.enabled_models_lookup("embed")
    if not embed_models_enabled:
        LOGGER.debug("Embedding Disabled (no Embedding Models)")
        st.error("No embedding models are configured and/or enabled. Disabling Embedding.", icon="🛑")
        st.stop()

    # Setup Corpus Sources
    file_sources = ["OCI", "Local", "Web", "SQL"]
    oci_lookup = helpers.state_configs_lookup("oci_configs", "auth_profile")
    auth_profile = state["settings"]["client_settings"].get("oci", {}).get("auth_profile")
    oci_setup = oci_lookup.get(auth_profile)
    if not oci_setup or oci_setup.get("namespace") is None or oci_setup.get("tenancy") is None:
        st.warning("OCI is not fully configured, some functionality is disabled", icon="⚠️")
        file_sources.remove("OCI")
        oci_setup = None

    return embed_models_enabled, file_sources, oci_setup


def _configure_vector_store_mode(embed_models_enabled: dict) -> tuple[bool, dict]:
    """Configure vector store creation mode and return embed config dict."""
    embed_config: dict = {}
    create_new_vs = True

    # Check for existing vector stores with enabled embedding models
    db_alias = state["settings"]["client_settings"].get("database", {}).get("alias")
    db_lookup = helpers.state_configs_lookup("database_configs", "alias")
    vector_stores = db_lookup.get(db_alias, {}).get("vector_stores", [])

    if vector_stores:
        vs_df = pd.DataFrame(vector_stores)
        # Build "provider/id" model column from embedding_model dict
        if "embedding_model" in vs_df.columns:
            vs_df["model"] = vs_df["embedding_model"].apply(
                lambda em: f"{em['provider']}/{em['id']}" if isinstance(em, dict) and em else ""
            )
        else:
            vs_df["model"] = ""
        vs_filtered = vs_df[vs_df["model"].isin(embed_models_enabled.keys())]
    else:
        vs_filtered = pd.DataFrame()

    if not vs_filtered.empty:
        create_new_vs = st.toggle(
            "Create New Vector Store",
            key="selected_create_new_vs",
            value=True,
            help="Toggle between creating a new vector store or adding to an existing one. "
            "When using an existing vector store, chunk size, overlap, distance strategy, "
            "and index type are already defined and cannot be changed.",
        )
        if not create_new_vs:
            vector_store_selection(location="main")

    if create_new_vs:
        _render_embedding_config_section(embed_models_enabled, embed_config)
    else:
        vs_settings = state["settings"]["client_settings"].get("vector_search", {})
        required_fields = ["alias", "chunk_size", "chunk_overlap", "distance_strategy", "index_type"]
        model_present = vs_settings.get("provider") and vs_settings.get("id")
        vs_missing = [f for f in required_fields if vs_settings.get(f) is None]
        if vs_missing or not model_present:
            st.stop()

    return create_new_vs, embed_config


#############################################################################
# MAIN
#############################################################################
def display_split_embed() -> None:
    """Streamlit GUI."""
    embed_models_enabled, file_sources, oci_setup = _initialize_and_validate_config()

    create_new_vs, embed_config = _configure_vector_store_mode(embed_models_enabled)

    source_data = _render_load_kb_section(file_sources, oci_setup)

    rate_limit = _render_populate_vs_section(embed_config, create_new_vs)

    if embed_config:
        _handle_vector_store_population(embed_config, source_data, rate_limit, create_new_vs)
