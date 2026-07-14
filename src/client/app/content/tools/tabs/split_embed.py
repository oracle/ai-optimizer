"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Split and Embed tab — document splitting, chunking, embedding, and vector store population.
"""
# spell-checker:ignore selectbox hnsw ivf iterrows isin ocid

import logging
import math
import re
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Optional

import httpx
import pandas as pd
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import APIError, api_get, api_patch, api_post
from client.app.core.embed_status import (
    _STAGE_LABELS,
    clear_embed_job_flag,
    mark_embed_job_started,
    render_active_embed_jobs,
)
from client.app.core.settings import settings as client_settings
from client.app.core.sidebar import vector_store_selection
from url_safety import validate_structural

LOGGER = logging.getLogger("client.content.tools.tabs.split_embed")

DISTANCE_STRATEGIES = ["COSINE", "DOT_PRODUCT", "EUCLIDEAN_DISTANCE"]
INDEX_TYPES = ["HNSW", "IVF", "HYB"]


#####################################################
# Inline Utilities
#####################################################
_REACHABLE_STATUSES = {200, 401, 403, 404, 421}
_MAX_PROBE_REDIRECTS = 5


@st.cache_data(ttl=30, show_spinner=False)
def _is_url_accessible(url: str, restricted: bool = False) -> tuple[bool, str]:
    """Check if a URL is reachable.

    ``restricted=True`` enables the user-supplied URL eligibility
    check: the URL (and every redirect target) must pass
    ``validate_safe_url``. Default mode is unrestricted and is used to
    probe admin-configured endpoints such as the embedding model
    ``api_base`` value, which legitimately resolves to local addresses.
    """
    if not url:
        return False, "No URL Provided"

    if restricted:
        # Structural-only — the application host may be behind a
        # proxy that owns external DNS, and the server re-validates
        # the URL with full DNS resolution before fetching.
        try:
            validate_structural(url)
        except ValueError:
            return False, "URL cannot be used for this import."

    try:
        with httpx.Client(timeout=2, follow_redirects=not restricted) as client:
            response = _probe_with_revalidation(client, url) if restricted else client.get(url)
    except httpx.HTTPError as ex:
        return False, f"{url} is not accessible. ({type(ex).__name__})"
    except ValueError:
        return False, "URL cannot be used for this import."

    if response is None or response.status_code not in _REACHABLE_STATUSES:
        status = f" (Status: {response.status_code})" if response is not None else ""
        return False, f"{url} is not accessible.{status}"
    return True, ""


def _probe_with_revalidation(client: httpx.Client, url: str) -> httpx.Response | None:
    """Issue a GET, validating every redirect target before following it."""
    current = url
    for _ in range(_MAX_PROBE_REDIRECTS + 1):
        response = client.get(current)
        if not response.is_redirect:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        # ``httpx.URL.join`` raises ``InvalidURL`` for malformed Location
        # values (e.g. ``http://[::1``). Treat those the same as a
        # failed probe so the Streamlit render does not crash.
        try:
            current = str(httpx.URL(current).join(location))
        except httpx.InvalidURL:
            return None
        validate_structural(current)
    return None


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
            "split_by_filename": embed_config.get("split_by_filename", False),
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
    oci_all_files: bool = False
    sql_query: Optional[str] = None
    sql_db_alias: Optional[str] = None

    def is_valid(self) -> bool:
        """Check if the current file source configuration is valid."""
        if self.file_source == "Local":
            return bool(state.get("runtime_local_file_uploader"))
        if self.file_source == "Web":
            return bool(self.web_url and _is_url_accessible(self.web_url, restricted=True)[0])
        if self.file_source == "SQL":
            return bool(self.sql_query and self.sql_query.strip() and self.sql_db_alias)
        if self.file_source == "OCI":
            if not self.oci_bucket:
                return False
            return bool(
                self.oci_all_files
                or (self.oci_files_selected is not None and self.oci_files_selected["Process"].sum() > 0)
            )
        return False

    def get_button_help(self) -> str:
        """Get help text for the populate button based on file source."""
        if self.file_source == "OCI" and self.oci_all_files:
            return "This button is disabled if no source bucket is selected."
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


@st.cache_data(ttl=60, show_spinner="Retrieving OCI Buckets")
def _get_buckets(compartment_ocid: str, auth_profile: str) -> list:
    """Get OCI bucket names in a compartment."""
    try:
        return api_get(f"oci/buckets/{compartment_ocid}/{auth_profile}")
    except httpx.HTTPStatusError:
        return ["No Access to Buckets in this Compartment"]


@st.cache_data(ttl=60, show_spinner="Listing bucket objects")
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

        pinned_compartment_id = client_settings.oci_source_bucket_compartment_id
        pinned_compartment_label = (
            next(
                (label for label, ocid in oci_compartments.items() if ocid == pinned_compartment_id),
                None,
            )
            if pinned_compartment_id
            else None
        )
        compartment_locked = pinned_compartment_label is not None

        col2_1, col2_2 = st.columns([0.5, 0.5])
        with col2_1:
            bucket_compartment = st.selectbox(
                "Bucket compartment:",
                [pinned_compartment_label] if compartment_locked else list(oci_compartments.keys()),
                index=0 if compartment_locked else None,
                placeholder=None if compartment_locked else "Select bucket compartment...",
                disabled=compartment_locked,
            )
            src_bucket_list = (
                _get_buckets(oci_compartments[bucket_compartment], auth_profile) if bucket_compartment else []
            )

        bucket_locked = compartment_locked and client_settings.oci_source_bucket_name in src_bucket_list

        with col2_2:
            data.oci_bucket = st.selectbox(
                "Source bucket:",
                [client_settings.oci_source_bucket_name] if bucket_locked else src_bucket_list,
                index=0 if bucket_locked else None,
                placeholder=None if bucket_locked else "Select source bucket...",
                disabled=bucket_locked or not bucket_compartment,
            )

        data.oci_all_files = st.toggle(
            "Embed all supported files in bucket",
            value=False,
            key="runtime_oci_all_files",
            disabled=not data.oci_bucket,
            help="When enabled, every supported file in the selected bucket is embedded.",
        )

        if data.oci_bucket:
            st.caption(state.optimizer_help.get("embed_supported_file_types", ""))
            if data.oci_all_files:
                st.caption(f"All supported files in `{data.oci_bucket}` will be embedded.")
            else:
                src_objects = _get_bucket_objects(data.oci_bucket, auth_profile)
                src_files = _files_data_frame(src_objects)
                data.oci_files_selected = _files_data_editor(src_files, "source")

    return data


def _render_filename_grouping_option(
    source_data: FileSourceData | None, create_new_vs: bool, embed_config: dict
) -> None:
    """Offer filename-grouped stores only for an explicit multi-file selection."""
    selected_count = 0
    if source_data is None:
        return
    elif source_data.file_source == "Local":
        selected_count = len(state.get("runtime_local_file_uploader") or [])
    elif source_data.file_source == "OCI" and source_data.oci_files_selected is not None:
        selected_count = int(source_data.oci_files_selected["Process"].sum())

    if create_new_vs and selected_count > 1:
        embed_config["split_by_filename"] = st.toggle(
            "Create one vector store per filename",
            value=False,
            key="selected_split_by_filename",
            help="Files with the same filename are added to the same vector store.",
        )
    else:
        embed_config["split_by_filename"] = False


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


def _render_populate_vs_section(
    embed_config: dict, create_new_vs: bool, source_data: FileSourceData | None
) -> int | None:
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
        _render_filename_grouping_option(source_data, create_new_vs, embed_config)
        if not embed_config.get("split_by_filename"):
            embed_config["alias"] = st.text_input(
                "Vector Store Alias:",
                max_chars=20,
                help=state.optimizer_help.get("embed_alias", ""),
                key="selected_embed_alias",
                placeholder="Enter a name for the new vector store",
            )
        else:
            embed_config["alias"] = None
            st.caption("Vector store aliases will be derived from the filenames.")
        if embed_config.get("split_by_filename"):
            vs_table = "One vector store per filename"
        elif embed_config["alias"] and not _validate_new_alias(embed_config["alias"]):
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

    if vs_table and not embed_config.get("split_by_filename"):
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
def _process_populate_request(
    embed_config: dict, source_data: FileSourceData, rate_limit: int | None
) -> tuple[str | None, dict]:
    """Store source files then run split-and-embed.

    Returns ``(job_id, response)``. ``job_id`` is ``None`` for the
    OCI no-files-selected fast path; otherwise it's the accepted
    submission id, also attached to any exception raised by the poll
    so the caller can clear that specific seen-set entry.
    """
    client_header = {"client": state.optimizer_client}
    auth_profile = state["settings"]["client_settings"].get("oci", {}).get("auth_profile", "")

    if source_data.file_source == "OCI":
        payload = _build_embed_payload(embed_config)
        payload["bucket_name"] = source_data.oci_bucket or ""
        payload["auth_profile"] = auth_profile or "DEFAULT"
        if not source_data.oci_all_files:
            oci_selected = source_data.oci_files_selected
            if oci_selected is None:
                return None, {}
            process_list = oci_selected[oci_selected["Process"]].reset_index(drop=True)
            object_names = process_list["File"].tolist()
            # An empty ``objects`` list is server-equivalent to omitting
            # it — i.e. "embed every supported file in the bucket".
            # Reject zero-selection here so a TOCTOU race past the
            # disabled-button gate cannot silently embed the whole bucket.
            if not object_names:
                return None, {}
            payload["objects"] = object_names
        # 7200s mirrors ``/embed/refresh`` (same synchronous-download
        # shape); /embed/oci/store downloads bucket objects before the
        # 202, so a ReadTimeout would lose the job_id mid-flight.
        accepted = api_post(
            "embed/oci/store",
            json=payload,
            params={"rate_limit": rate_limit or 0},
            extra_headers=client_header,
            timeout=7200,
        )
        job_id = accepted["job_id"]
        mark_embed_job_started(job_id)
        try:
            return job_id, _poll_embed_job(job_id, client_header)
        except httpx.HTTPStatusError as ex:
            ex.job_id = job_id  # type: ignore[attr-defined]
            raise

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

    # Step 2: Split and embed — schedule the job and poll for terminal state.
    # 300s acceptance timeout outlasts pre-202 latency (``_settings_lock``
    # contention with a slow connection test, slow CORE INSERT). A
    # ``ReadTimeout`` here while the server still completes
    # ``manager.submit`` would lose the job_id and leave a running
    # job the user cannot poll.
    payload = _build_embed_payload(embed_config)
    accepted = api_post(
        "embed/",
        json=payload,
        params={"rate_limit": rate_limit or 0},
        extra_headers=client_header,
        timeout=300,
    )
    # Add the job_id to the panel's seen set the moment the server
    # accepts the submission, so off-page completions still trigger
    # ``refresh_on_idle`` even when no fragment tick observed the
    # running state.
    job_id = accepted["job_id"]
    mark_embed_job_started(job_id)
    try:
        return job_id, _poll_embed_job(job_id, client_header)
    except httpx.HTTPStatusError as ex:
        # Attach so the caller's except branch can clear this
        # specific seen-set entry without disturbing any concurrent
        # sibling jobs the panel is also tracking.
        ex.job_id = job_id  # type: ignore[attr-defined]
        raise


_POLL_INTERVAL_SECONDS = 2.0
# 503 tolerance window. The status endpoint returns 503 when the
# CORE database is briefly unavailable for cross-replica state
# tracking; the pipeline itself is still running on the server side,
# so a transient blip should not abort the UI. Cap the consecutive
# count so a permanent CORE outage eventually surfaces instead of
# spinning forever — at the default 2s poll interval this is a few
# minutes of patience before giving up.
_MAX_CONSECUTIVE_503S = 60


def _poll_embed_job(job_id: str, client_header: dict) -> dict:
    """Block until the embed job reaches terminal status, updating spinner text.

    Each request is short, so neither the load balancer nor nginx can
    time us out — the only ceiling is that the job itself eventually
    succeeds or fails. A failure raises ``httpx.HTTPStatusError`` shaped
    like the old synchronous error path so the calling render code can
    keep using ``helpers.extract_error_detail``.

    Transient failures are absorbed up to ``_MAX_CONSECUTIVE_503S``
    consecutive blips; the pipeline is server-side and continues to
    make progress while we back off and retry. The retry budget
    covers two distinct shapes:

    * **HTTP 503** — the status endpoint returned, but CORE is
      momentarily unavailable for cross-replica state tracking.
    * **Transport error** — ``httpx.TimeoutException`` /
      ``httpx.TransportError`` (no response received). The CORE
      read can stall longer than this client's 15s timeout, and
      a brief network blip surfaces the same way; treating these
      as terminal would abort polling for a job that is still
      running. ``TransportError`` is the parent of all
      non-status httpx failures so this single ``except`` covers
      timeouts, connection resets, and proxy errors.

    Other HTTP errors (401 / 404 / 500-non-503) propagate
    immediately — those mean something structural is wrong and
    retrying would just spin.
    """
    last_message: str | None = None
    consecutive_transient_failures = 0
    while True:
        try:
            info = api_get(
                f"embed/jobs/{job_id}",
                extra_headers=client_header,
                timeout=15,
            )
        except httpx.HTTPStatusError as ex:
            if ex.response.status_code == 503:
                consecutive_transient_failures += 1
                if consecutive_transient_failures > _MAX_CONSECUTIVE_503S:
                    raise
                LOGGER.warning(
                    "Embed job %s polling: CORE unavailable (503), retry %d/%d",
                    job_id,
                    consecutive_transient_failures,
                    _MAX_CONSECUTIVE_503S,
                )
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            raise
        except (httpx.TransportError, APIError) as ex:
            # No HTTP response received (timeout, connection reset,
            # proxy error; APIError is the api-layer translation of the
            # same). Same retry contract as 503: the server-side job is
            # still running, back off and retry rather than aborting the
            # poll loop.
            consecutive_transient_failures += 1
            if consecutive_transient_failures > _MAX_CONSECUTIVE_503S:
                # Convert the exhausted-budget transport failure into
                # an ``HTTPStatusError`` so the populate-request UI's
                # ``except httpx.HTTPStatusError`` handler picks it up.
                # Re-raising ``TransportError`` directly would bypass
                # that catch and surface as an uncaught Streamlit
                # exception. 503 mirrors the "CORE unavailable"
                # status — the user sees a normal error message and
                # can retry once connectivity is back. The original
                # transport error chains through ``__cause__`` so
                # diagnostic logs still see what actually happened.
                detail = (
                    f"Lost contact with the embed-job status endpoint "
                    f"after {consecutive_transient_failures - 1} retries "
                    f"({type(ex).__name__}: {ex}); the job may still be "
                    f"running server-side."
                )
                request = httpx.Request("GET", f"embed/jobs/{job_id}")
                response = httpx.Response(503, json={"detail": detail}, request=request)
                raise httpx.HTTPStatusError(detail, request=request, response=response) from ex
            LOGGER.warning(
                "Embed job %s polling: transport failure (%s: %s), retry %d/%d",
                job_id,
                type(ex).__name__,
                ex,
                consecutive_transient_failures,
                _MAX_CONSECUTIVE_503S,
            )
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
        consecutive_transient_failures = 0

        status = info.get("status")
        progress = info.get("progress") or {}
        stage = progress.get("stage", status)
        label = _STAGE_LABELS.get(stage, stage or "Working")
        message = progress.get("message") or ""
        rendered = f"{label}{(' — ' + message) if message else ''}"
        if rendered != last_message:
            last_message = rendered
            # st.spinner is one-shot, so emit progress as a toast that
            # appends below the spinner without re-rendering it. The
            # log line stays for diagnostics; the toast is what the
            # user actually sees during a long-running job.
            LOGGER.debug("embed job %s: %s", job_id, rendered)
            st.toast(rendered)
        if status == "succeeded":
            return info["result"] or {}
        if status == "failed":
            error = info.get("error") or "Embedding job failed."
            # Synthesise an httpx error so callers can keep extracting
            # the detail with the existing helper used by the inline path.
            request = httpx.Request("GET", f"embed/jobs/{job_id}")
            response = httpx.Response(500, json={"detail": error}, request=request)
            raise httpx.HTTPStatusError(error, request=request, response=response)
        time.sleep(_POLL_INTERVAL_SECONDS)


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

    if not embed_config.get("alias") and create_new_vs and not embed_config.get("split_by_filename"):
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
            state.running = not (
                is_source_valid and (embed_config.get("vector_store") or embed_config.get("split_by_filename"))
            )
            populate_clicked = st.button(
                "Populate Vector Store",
                type="primary",
                icon="📤",
                key="button_populate",
                disabled=state.running,
                help=source_data.get_button_help(),
            )

    return populate_clicked, refresh_clicked


def _handle_populate_success(job_id: str | None, response: dict) -> None:
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

    # Only clear on confirmed-successful refresh; on failure the panel
    # retries on its next 2-second tick.
    if helpers.refresh_settings() and job_id is not None:
        clear_embed_job_flag(job_id)


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
    # The /embed/refresh endpoint is synchronous and adds nothing to
    # the panel's seen set, so this path must not call
    # clear_embed_job_flag — it would only harm unrelated tracked jobs.
    helpers.refresh_settings()


def _handle_vector_store_population(
    embed_config: dict, source_data: FileSourceData, rate_limit: int | None, create_new_vs: bool
) -> None:
    """Handle vector store population button and processing."""
    populate_clicked, refresh_clicked = _render_population_button(embed_config, source_data, create_new_vs)

    if populate_clicked:
        try:
            with st.spinner("Populating Vector Store... please be patient.", show_time=True):
                job_id, response = _process_populate_request(embed_config, source_data, rate_limit)
            _handle_populate_success(job_id, response)
        except httpx.HTTPStatusError as ex:
            # 503 = synthesised "retry budget exhausted; the job may
            # still be running" — keep the seen-set entry. Anything
            # else is a definite terminal failure for this id.
            # ``ex.job_id`` is attached by _process_populate_request
            # only after the POST 202 succeeded; pre-202 errors have
            # no attached id and no seen-set entry to clear.
            attached_id = getattr(ex, "job_id", None)
            if ex.response.status_code != HTTPStatus.SERVICE_UNAVAILABLE and attached_id is not None:
                clear_embed_job_flag(attached_id)
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

    rate_limit = _render_populate_vs_section(embed_config, create_new_vs, source_data)

    if embed_config:
        _handle_vector_store_population(embed_config, source_data, rate_limit, create_new_vs)

    # ``refresh_on_idle`` is needed even though the synchronous flow
    # already refreshes on success: a user who navigates away mid-poll
    # kills the synchronous loop, leaving the fragment as the only
    # completion observer when they return.
    render_active_embed_jobs(refresh_on_idle=True, hide_when_idle=True)
