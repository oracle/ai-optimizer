"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Embed endpoints — file storage, document splitting, vector store population, and refresh.
"""
# spell-checker:ignore docos slugified webscrape

import asyncio
import contextlib
import datetime
import json
import logging
import lzma
import os
import shutil
import tempfile
import zipfile
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import HttpUrl

from server.app.api.v1.endpoints.oci import _find_oci_profile
from server.app.api.v1.schemas.chat import MessageResponse
from server.app.api.v1.schemas.common import ClientId
from server.app.api.v1.schemas.embed import (
    EmbedProcessingResult,
    SqlStoreRequest,
    VectorStoreRefreshRequest,
    VectorStoreRefreshStatus,
)
from server.app.core.error_detail import response_error_detail
from server.app.core.file_utils import get_temp_directory, safe_filename
from server.app.core.settings import resolve_client, settings
from server.app.database.config import get_client_db_config as _resolve_db_config
from server.app.database.config import get_database_settings
from server.app.database.registry import discover_vector_stores, drop_vector_store
from server.app.database.sql import execute_sql
from server.app.embed.document import load_and_split_documents
from server.app.embed.refresh import refresh_vector_store_from_bucket
from server.app.embed.schemas import VectorStoreConfig
from server.app.embed.utils import run_sql_query
from server.app.embed.vector_store import (
    generate_vs_metadata,
    get_processed_objects_metadata,
    get_total_chunks_count,
    get_vector_store_by_alias,
    get_vector_store_files,
    populate_vs,
    update_vs_comment,
)
from server.app.embed.webscrape import fetch_and_extract_sections, slugify
from server.app.mcp.tools.schemas import get_oci_profile
from server.app.models.litellm_utils import get_client_embed
from server.app.oci.bucket import (
    SUPPORTED_EXTENSIONS,
    detect_changed_objects,
    get_bucket_objects_with_metadata,
)
from url_safety import SafeAsyncClient, validate_structural

LOGGER = logging.getLogger(__name__)


# Per-client lock guarding mutations of the shared embedding temp
# directory. Both `store_local_file` (full upload) and `split_embed`
# (`_prepare_work_dir`) acquire the lock for the same client so the
# backup/rename sequence in `_promote_atomically` cannot race with a
# concurrent move-out of the same files. The registry is an LRU
# bounded by `settings.max_clients` so a long-lived process cannot
# accumulate locks for every transient Client header value seen.
@dataclass
class _LockEntry:
    """Registry entry pairing a per-client lock with an in-use refcount.

    `users` counts everyone currently inside `_client_lock(client)` —
    both the holder and any queued waiters. The count is mutated only
    under `_client_locks_guard`, so eviction can safely treat
    ``users == 0`` as "no in-flight request relies on this entry" and
    skip everything else. This is strictly tighter than checking
    ``lock.locked()``: ``asyncio.Lock`` has a brief handoff window
    between ``release()`` and a woken waiter resuming where ``locked()``
    is False even though a waiter is queued, and evicting in that
    window would let a subsequent request for the same client allocate
    a second Lock and run concurrently with the still-pending waiter.
    """

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


_client_promotion_locks: OrderedDict[str, _LockEntry] = OrderedDict()
_client_locks_guard = asyncio.Lock()


@contextlib.asynccontextmanager
async def _client_lock(client: str):
    """Per-client serialisation around shared embedding temp dir mutations.

    Indexes by the same canonical form `get_temp_directory` uses
    (`safe_filename(client)`) so two raw header values that resolve to
    the same on-disk directory share one lock. Without this, e.g.
    ``Client: team/a`` and ``Client: a`` would lock independently while
    operating on the same files in `<base>/a/embedding`.

    Caps the registry at ``settings.max_clients`` entries with LRU
    eviction. Entries with ``users > 0`` are skipped during eviction
    so an in-flight request — holder *or* queued waiter — retains its
    mutual-exclusion guarantee even when the registry is under
    pressure.
    """
    key = safe_filename(client)
    async with _client_locks_guard:
        entry = _client_promotion_locks.get(key)
        if entry is None:
            cap = max(1, settings.max_clients)
            while len(_client_promotion_locks) >= cap:
                evict_key = next(
                    (k for k, e in _client_promotion_locks.items() if e.users == 0),
                    None,
                )
                if evict_key is None:
                    # Every entry is in use; accept temporary growth
                    # rather than break in-flight serialisation.
                    break
                _client_promotion_locks.pop(evict_key)
            entry = _LockEntry()
            _client_promotion_locks[key] = entry
        else:
            _client_promotion_locks.move_to_end(key)
        # Increment under the guard so a waiter is counted *before* it
        # awaits `entry.lock` — eviction will see users >= 1 even
        # during the asyncio release/resume handoff window.
        entry.users += 1
    try:
        async with entry.lock:
            yield
    finally:
        async with _client_locks_guard:
            entry.users -= 1


# ZIP extraction limits
_ZIP_MAX_FILES = 500
_ZIP_MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB total decompressed
_ZIP_MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB per file
_ZIP_STREAM_CHUNK = 64 * 1024  # copy buffer for streaming zip extraction
_ZIP_BLOCKED_EXTENSIONS = frozenset({".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar"})

_METADATA_FILENAME = ".file_metadata.json"

_WEB_FETCH_TIMEOUT = 60.0  # seconds

# Map Content-Type prefixes to file extensions for extensionless URLs.
_CONTENT_TYPE_TO_EXT: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "image/png": ".png",
    "image/jpeg": ".jpeg",
}

auth = APIRouter(prefix="/embed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _promote_atomically(names, staging: Path, dest: Path, detail: str) -> None:
    """Move *names* from *staging* into *dest* with rollback on OSError.

    Before each move, any file already at ``dest / name`` is stashed in
    a private sub-directory of *staging* (created via ``mkdtemp`` so
    its name cannot collide with any staged member basename, including
    contrived names like ``.backup_foo.txt``).  A later mid-loop
    OSError restores every touched destination to its pre-call bytes
    rather than leaving whichever copy happened to win the last rename.
    On successful completion the backup sub-directory is removed along
    with *staging* by the caller's ``shutil.rmtree``.  Failure raises
    :class:`HTTPException` (500) with *detail* once every reachable
    backup has been restored and every new file undone.

    *names* is any iterable of basename strings — iterating ``dict``
    keys is the intended call site.
    """
    backup_dir = Path(tempfile.mkdtemp(dir=staging, prefix=".backup_"))
    backups: dict[Path, Path] = {}  # dst_path -> backup_path
    promoted: list[Path] = []

    def _rollback() -> None:
        # Clear any new file we wrote (promoted or not), then restore
        # the backed-up original. Suppressed failures are best-effort —
        # the subsequent rmtree of `backup_dir` will at worst leave
        # dest empty for a name whose backup could not be moved back.
        touched = set(backups) | set(promoted)
        for dst_path in touched:
            with contextlib.suppress(OSError):
                dst_path.unlink(missing_ok=True)
            backup_path = backups.get(dst_path)
            if backup_path is not None and backup_path.exists():
                with contextlib.suppress(OSError):
                    shutil.move(str(backup_path), str(dst_path))

    try:
        for name in names:
            dst_path = dest / name
            # A directory at dst would otherwise be silently moved into
            # the backup dir and replaced with our staged file —
            # concurrent split_embed work_dirs and other in-flight
            # subdirectories must not be clobbered.
            if dst_path.is_dir():
                _rollback()
                raise HTTPException(
                    status_code=409,
                    detail=(f"Cannot store '{name}': a directory with that name already exists in the temp directory."),
                )
            backup_path = backup_dir / name
            try:
                shutil.move(str(dst_path), str(backup_path))
            except FileNotFoundError:
                pass  # nothing pre-existing to back up
            else:
                backups[dst_path] = backup_path
            shutil.move(str(staging / name), str(dst_path))
            promoted.append(dst_path)
    except OSError as ex:
        _rollback()
        raise HTTPException(status_code=500, detail=detail) from ex
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _extract_zip(zip_path: Path, dest: Path) -> dict:
    """Extract *zip_path* into *dest* with safety limits; return per-file metadata.

    Extraction is atomic per-archive: members are written into a staging
    sub-directory of *dest*, then moved into *dest* only after every
    member has been read and validated.  A failure at any point (size
    cap, CRC mismatch, decompression error, I/O error) removes the
    staging directory and leaves *dest* exactly as it was on entry —
    including any pre-existing file whose basename collides with an
    archive member.  Corrupt uploads surface as :class:`HTTPException`
    (400) rather than :class:`zipfile.BadZipFile`, so the caller's
    generic error handling does not silently swallow them.
    """
    # The constructor itself can raise before `infolist` is reached:
    # BadZipFile for a missing / corrupt end-of-central-directory,
    # NotImplementedError for an unsupported extract version or
    # compression method advertised in the central directory, and
    # RuntimeError / OSError for other header parse failures. Archive
    # parse/read errors are returned as HTTP 400; filesystem write
    # errors remain HTTP 500.
    try:
        zip_ref = zipfile.ZipFile(zip_path, "r")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as ex:
        raise HTTPException(status_code=400, detail="Upload is not a valid ZIP archive.") from ex

    with zip_ref:
        # Wrap every path that can raise from corrupt archive data —
        # infolist (central directory parse), open(info) (local header
        # parse), and the copyfileobj read loop (decompressor output) —
        # in one handler so BadZipFile AND zlib.error both become HTTP
        # 400 instead of becoming generic 500s.
        try:
            members = [m for m in zip_ref.infolist() if not m.filename.endswith("/")]
            if len(members) > _ZIP_MAX_FILES:
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP exceeds max file count ({_ZIP_MAX_FILES}).",
                )
            total_size = sum(m.file_size for m in members)
            if total_size > _ZIP_MAX_TOTAL_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=(f"ZIP decompressed size exceeds limit ({_ZIP_MAX_TOTAL_BYTES // (1024 * 1024)} MB)."),
                )

            for info in members:
                if info.file_size > _ZIP_MAX_FILE_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"File {info.filename} exceeds per-file size limit "
                            f"({_ZIP_MAX_FILE_BYTES // (1024 * 1024)} MB)."
                        ),
                    )

            # All caps passed — stage members under a private sub-directory
            # of dest so a mid-extraction failure cannot clobber any file
            # already present in dest.
            metadata: dict = {}
            staging = Path(tempfile.mkdtemp(dir=dest, prefix=".zipextract_"))
            try:
                for info in members:
                    member_name = os.path.basename(info.filename)
                    if not member_name or Path(member_name).suffix.lower() in _ZIP_BLOCKED_EXTENSIONS:
                        continue
                    staging_path = staging / member_name
                    # `zip_ref.open(info)` surfaces user-input archive
                    # problems before any bytes are decompressed:
                    # RuntimeError for encrypted members, NotImplementedError
                    # for unsupported compression methods, and OSError for
                    # certain local-header corruptions.  Translate them to
                    # 400 here so the outer handler can keep treating
                    # OSError from disk writes (staging_path.open, stat,
                    # target.write) as 500.
                    try:
                        source_cm = zip_ref.open(info)
                    except (RuntimeError, NotImplementedError, OSError) as ex:
                        raise HTTPException(
                            status_code=400,
                            detail="ZIP archive is corrupt or unreadable.",
                        ) from ex
                    # Stream member bytes, isolating the read side so a
                    # corrupt DEFLATE / bzip2 / LZMA stream surfaces as
                    # 400 instead of 500. bz2 raises plain OSError, lzma
                    # raises lzma.LZMAError, and DEFLATE raises
                    # zlib.error — none of which inherit from
                    # BadZipFile, so the outer handler would otherwise
                    # expose implementation errors. The write side stays uncaught: ENOSPC
                    # / EROFS / etc. on the target are real server
                    # failures and must remain 500.
                    with source_cm as source, staging_path.open("wb") as target:
                        while True:
                            try:
                                chunk = source.read(_ZIP_STREAM_CHUNK)
                            except (OSError, zlib.error, lzma.LZMAError) as ex:
                                raise HTTPException(
                                    status_code=400,
                                    detail="ZIP archive is corrupt or unreadable.",
                                ) from ex
                            if not chunk:
                                break
                            target.write(chunk)

                    stat_result = staging_path.stat()
                    metadata[member_name] = {
                        "size": stat_result.st_size,
                        "time_modified": datetime.datetime.fromtimestamp(
                            stat_result.st_mtime, datetime.timezone.utc
                        ).isoformat(),
                    }
                # Every member extracted cleanly — promote into dest.
                # Colliding pre-existing files are backed up first and
                # restored on any mid-promotion OSError, so dest is
                # left either fully updated or untouched.
                _promote_atomically(metadata, staging, dest, detail="Failed to finalise archive extraction.")
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        except (zipfile.BadZipFile, zlib.error) as ex:
            raise HTTPException(
                status_code=400,
                detail="ZIP archive is corrupt or unreadable.",
            ) from ex
    return metadata


async def _save_web_sections(url: str, temp_directory: Path) -> None:
    """Fetch HTML from *url* and write each section as a text file."""
    sections = await fetch_and_extract_sections(url)
    base = slugify(url.rsplit("/", maxsplit=1)[-1]) or "page"
    for idx, sec in enumerate(sections, 1):
        stub = slugify(sec.get("title", "")) if sec.get("title") else base
        with open(temp_directory / f"{stub}-section{idx}.txt", "w", encoding="utf-8", errors="replace") as f:
            if sec.get("title"):
                f.write(sec["title"].strip() + "\n\n")
            f.write(str(sec["content"]).strip())


def _prepare_work_dir(temp_directory: Path, work_dir: Path, client: str) -> list[Path]:
    """Move files from *temp_directory* into *work_dir* and return the file list.

    Restores files on error and raises HTTPException on failure.
    """
    try:
        for item in temp_directory.iterdir():
            if item.is_file():
                shutil.move(str(item), work_dir / item.name)
    except FileNotFoundError as exc:
        for rescued in work_dir.iterdir():
            if rescued.is_file():
                shutil.move(str(rescued), temp_directory / rescued.name)
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=404,
            detail=f"Embed: Client {client} documents folder not found.",
        ) from exc

    files = [f for f in work_dir.iterdir() if f.is_file() and f.name != _METADATA_FILENAME]
    if not files:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=404,
            detail=f"Embed: Client {client} no files found in folder.",
        )
    return files


def _load_file_metadata(work_dir: Path):
    """Load .file_metadata.json from *work_dir* if it exists, else return None."""
    metadata_path = work_dir / _METADATA_FILENAME
    if not metadata_path.exists():
        return None
    try:
        with metadata_path.open("r") as f:
            metadata = json.load(f)
        LOGGER.info("Loaded metadata for %d files", len(metadata))
        return metadata
    except Exception as ex:
        LOGGER.warning("Could not load file metadata: %s", ex)
        return None


def _get_client_db_config(client: str):
    """Resolve the client's database config with pool validation.

    Returns (db_config, pool) — pool is guaranteed non-None.
    """
    db_config = _resolve_db_config(client)
    if db_config is None:
        cs = resolve_client(client)
        raise HTTPException(status_code=503, detail=f"Database is not available: {cs.database.alias}")
    if db_config.pool is None:
        raise HTTPException(status_code=503, detail=f"Database pool is not available: {db_config.alias}")
    return db_config, db_config.pool


# ---------------------------------------------------------------------------
# DELETE /{vs}
# ---------------------------------------------------------------------------


@auth.delete(
    "/{vs}",
    description="Drop Vector Store",
    response_model=MessageResponse,
)
async def embed_drop_vs(
    vs: str,
    client: Annotated[ClientId, Header()] = "server",
) -> MessageResponse:
    """Drop a vector store table."""
    LOGGER.debug("Received %s embed_drop_vs: %s", client, vs)
    db_config, pool = _get_client_db_config(client)
    try:
        async with pool.acquire() as conn:
            # Check the table exists as a GENAI vector store without requiring
            # parseable metadata — allows cleanup of corrupted entries.
            rows = await execute_sql(
                conn,
                """SELECT 1 FROM all_tab_comments
                    WHERE table_name = :name AND comments LIKE 'GENAI:%'""",
                {"name": vs},
            )
            if not rows:
                raise HTTPException(status_code=404, detail=f"Vector store not found: {vs}")
            await drop_vector_store(conn, vs)
            # Re-discover after drop so the cache reflects current state.
            live_stores = await discover_vector_stores(conn)
    except HTTPException:
        raise
    except Exception as ex:
        LOGGER.error("embed_drop_vs failed: %s", ex)
        raise HTTPException(status_code=500, detail="Embed: an unexpected error occurred.") from ex
    db_config.vector_stores = list(live_stores)
    return MessageResponse(message=f"Vector Store: {vs} dropped.")


# ---------------------------------------------------------------------------
# GET /{vs}/files
# ---------------------------------------------------------------------------


@auth.get(
    "/{vs}/files",
    description="Get list of files embedded in a Vector Store",
)
async def embed_get_files(
    vs: str,
    client: Annotated[ClientId, Header()] = "server",
) -> JSONResponse:
    """Get list of files in a vector store with statistics."""
    LOGGER.debug("Received %s embed_get_files: %s", client, vs)
    _, pool = _get_client_db_config(client)
    try:
        async with pool.acquire() as conn:
            file_list = await get_vector_store_files(conn, vs)
        return JSONResponse(status_code=200, content=file_list)
    except Exception as ex:
        LOGGER.error("Error retrieving file list from %s: %s", vs, str(ex))
        raise HTTPException(status_code=500, detail="Could not retrieve file list.") from ex


# ---------------------------------------------------------------------------
# PATCH /comment
# ---------------------------------------------------------------------------


@auth.patch(
    "/comment",
    description="Update existing Vector Store Comment.",
    response_model=MessageResponse,
)
async def comment_vs(
    request: VectorStoreConfig,
    client: Annotated[ClientId, Header()] = "server",
) -> MessageResponse:
    """Update the comment on an existing vector store."""
    LOGGER.info("Received comment_vs - request: %s", request)
    _, pool = _get_client_db_config(client)

    if not request.embedding_model or request.distance_strategy is None:
        raise HTTPException(status_code=400, detail="embedding_model and distance_strategy are required")

    # Generate comment JSON from the vector store metadata
    _, comment_json = generate_vs_metadata(
        embedding_model=request.embedding_model,
        chunk_size=request.chunk_size or 0,
        chunk_overlap=request.chunk_overlap or 0,
        distance_strategy=request.distance_strategy,
        index_type=request.index_type or "HNSW",
        alias=request.alias,
        description=request.description,
    )

    async with pool.acquire() as conn:
        await update_vs_comment(conn, request, comment_json)

    return MessageResponse(message="Vector Store comment updated.")


# ---------------------------------------------------------------------------
# POST /sql/store
# ---------------------------------------------------------------------------


@auth.post(
    "/sql/store",
    description="Store SQL field for Embedding.",
)
async def store_sql_file(
    request: SqlStoreRequest,
    client: Annotated[ClientId, Header()] = "server",
) -> JSONResponse:
    """Store contents from a SQL query result as a file for embedding."""
    LOGGER.debug("Received store_sql_file - query: %s, db_alias: %s", request.query, request.db_alias)
    if request.db_alias:
        db_config = get_database_settings(settings.database_configs, request.db_alias)
        if db_config is None or not db_config.pool or not db_config.usable:
            raise HTTPException(status_code=503, detail=f"Database is not available: {request.db_alias}")
    else:
        db_config, _ = _get_client_db_config(client)
    temp_directory = get_temp_directory(client, "embedding")

    try:
        result_file = await run_sql_query(db_config, request.query, str(temp_directory))
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    if not result_file:
        raise HTTPException(status_code=400, detail="SQL query failed or returned no results.")

    stored_files = [os.path.basename(result_file)]
    LOGGER.debug("sql ingest - temp csv file location: %s", result_file)
    return JSONResponse(status_code=200, content=stored_files)


# ---------------------------------------------------------------------------
# POST /web/store
# ---------------------------------------------------------------------------


@auth.post(
    "/web/store",
    description="Store Web Files for Embedding.",
)
async def store_web_file(
    request: list[HttpUrl],
    client: Annotated[ClientId, Header()] = "server",
) -> JSONResponse:
    """Store contents from web URLs for embedding."""
    LOGGER.debug("Received store_web_file - request: %s", request)
    temp_directory = get_temp_directory(client, "embedding")

    # Pre-validate every input so a single bad entry rejects the whole
    # batch before any network I/O happens. ``validate_structural``
    # skips DNS resolution; full eligibility (including resolved
    # addresses) is re-checked by ``SafeAsyncClient`` per hop, taking
    # proxy mounts into account.
    try:
        for url in request:
            validate_structural(str(url))
    except ValueError as ex:
        raise HTTPException(status_code=400, detail="URL not permitted.") from ex

    async with SafeAsyncClient(timeout=_WEB_FETCH_TIMEOUT) as http_client:
        for url in request:
            filename = Path(urlparse(str(url)).path).name or slugify(str(url)) or "download"
            LOGGER.debug("Requesting: %s", url)

            try:
                async with http_client.stream("GET", str(url)) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("Content-Type", "").lower()
                    ext = Path(filename).suffix.lower()

                    # For extensionless URLs, infer ext from content-type
                    if not ext or ext not in SUPPORTED_EXTENSIONS:
                        for ct_prefix, ct_ext in _CONTENT_TYPE_TO_EXT.items():
                            if ct_prefix in content_type:
                                ext = ct_ext
                                filename = f"{Path(filename).stem}{ext}"
                                break

                    if any(ct in content_type for ct in _CONTENT_TYPE_TO_EXT):
                        # Content-Type identifies a specific supported format —
                        # trust it over the URL extension (e.g. a .html URL that
                        # actually serves application/pdf).
                        ct_ext = next(ct_ext for ct, ct_ext in _CONTENT_TYPE_TO_EXT.items() if ct in content_type)
                        if ext != ct_ext:
                            ext = ct_ext
                            filename = f"{Path(filename).stem}{ext}"
                        with open(temp_directory / filename, "wb") as file:
                            async for chunk in response.aiter_bytes():
                                file.write(chunk)
                    elif (
                        "html" in content_type
                        or "xhtml" in content_type
                        or (ext in {".html", ".xhtml"} and "application/octet-stream" not in content_type)
                    ):
                        # HTML/XHTML response — scrape sections
                        await _save_web_sections(str(url), temp_directory)
                    elif ext in SUPPORTED_EXTENSIONS or "application/octet-stream" in content_type:
                        # Supported document type or generic binary — save for the embed pipeline
                        with open(temp_directory / filename, "wb") as file:
                            async for chunk in response.aiter_bytes():
                                file.write(chunk)
                    elif "text" in content_type:
                        await _save_web_sections(str(url), temp_directory)
                    else:
                        raise HTTPException(
                            status_code=422,
                            detail=f"Unsupported file type: {ext or content_type}.",
                        )
            except ValueError as ex:
                raise HTTPException(status_code=400, detail="URL not permitted.") from ex

    stored_files = [f.name for f in temp_directory.iterdir() if f.is_file()]
    return JSONResponse(status_code=200, content=stored_files)


# ---------------------------------------------------------------------------
# POST /local/store
# ---------------------------------------------------------------------------


@auth.post(
    "/local/store",
    description="Store Local Files for Embedding.",
)
async def store_local_file(
    files: list[UploadFile] = File(...),
    client: Annotated[ClientId, Header()] = "server",
) -> JSONResponse:
    """Store uploaded local files for embedding (supports ZIP extraction).

    The entire batch is staged under a private sub-directory of the
    client's embedding temp directory and promoted atomically only after
    every upload (and every ZIP extraction) has succeeded. A mid-batch
    failure removes the staging directory and leaves the shared temp
    directory — including files from prior /local/store requests — in
    its pre-request state.
    """
    LOGGER.debug("Received store_local_file - files: %s", files)
    temp_directory = get_temp_directory(client, "embedding")

    # Acquire the per-client lock *before* any staging directory exists.
    # Holding it across the full upload (staging → promotion) means a
    # concurrent split_embed cannot enter `_prepare_work_dir` and find
    # an empty temp_directory mid-upload, which would otherwise return
    # 404 even as our request is about to land its files.
    async with _client_lock(client):
        request_staging = Path(tempfile.mkdtemp(dir=temp_directory, prefix=".request_"))
        try:
            file_metadata: dict = {}
            for upload_file in files:
                if not upload_file.filename:
                    continue
                staged_name = request_staging / safe_filename(upload_file.filename)
                file_content = await upload_file.read()
                with staged_name.open("wb") as f:
                    f.write(file_content)

                if staged_name.suffix.lower() == ".zip":
                    LOGGER.info("Extracting zip file: %s", staged_name.name)
                    file_metadata.update(_extract_zip(staged_name, request_staging))
                    staged_name.unlink()
                    LOGGER.info("Successfully extracted zip file: %s", upload_file.filename)
                else:
                    file_metadata[upload_file.filename] = {
                        "size": len(file_content),
                        "time_modified": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }

            # Write metadata into staging so it promotes atomically with the files.
            with (request_staging / _METADATA_FILENAME).open("w") as f:
                json.dump(file_metadata, f)

            # Metadata is promoted *last* so a concurrent
            # `_prepare_work_dir` on the shared temp directory never
            # sees metadata without the documents it describes.
            staged_names = sorted(item.name for item in request_staging.iterdir() if item.is_file())
            ordered_names = [n for n in staged_names if n != _METADATA_FILENAME]
            if _METADATA_FILENAME in staged_names:
                ordered_names.append(_METADATA_FILENAME)
            _promote_atomically(
                ordered_names,
                request_staging,
                temp_directory,
                detail="Failed to finalise upload to temporary directory.",
            )
        finally:
            shutil.rmtree(request_staging, ignore_errors=True)

    stored_files = [f.name for f in temp_directory.iterdir() if f.is_file() and f.name != _METADATA_FILENAME]
    return JSONResponse(status_code=200, content=stored_files)


# ---------------------------------------------------------------------------
# POST / (split and embed)
# ---------------------------------------------------------------------------


@auth.post(
    "/",
    description="Split and Embed Corpus.",
    response_model=EmbedProcessingResult,
)
async def split_embed(
    request: VectorStoreConfig,
    rate_limit: int = 0,
    client: Annotated[ClientId, Header()] = "server",
) -> EmbedProcessingResult:
    """Load stored files, split them into chunks, embed, and populate the vector store."""
    LOGGER.debug("Received split_embed - rate_limit: %i; request: %s", rate_limit, request)
    db_config, pool = _get_client_db_config(client)

    if not request.embedding_model or request.distance_strategy is None:
        raise HTTPException(status_code=400, detail="embedding_model and distance_strategy are required")
    oci_profile = get_oci_profile(client)
    work_dir = get_temp_directory(client, "embedding", unique=True)

    # `_prepare_work_dir` moves every file out of the shared embedding
    # temp directory; serialize it on the same per-client lock as
    # `store_local_file`'s promotion so the two cannot race on the same
    # basenames.
    async with _client_lock(client):
        files = await asyncio.to_thread(_prepare_work_dir, get_temp_directory(client, "embedding"), work_dir, client)
    LOGGER.info("Processing Files: %s", files)
    file_metadata = await asyncio.to_thread(_load_file_metadata, work_dir)

    try:
        split_docos, _, processing_results = await asyncio.to_thread(
            load_and_split_documents,
            files,
            f"{request.embedding_model.provider}/{request.embedding_model.id}",
            request.chunk_size or 0,
            request.chunk_overlap or 0,
            write_json=False,
            output_dir=None,
            file_metadata=file_metadata,
            parsing_mode=request.parsing_mode or "fast",
        )

        # Generate the vector store table name and comment
        request.vector_store, comment_json = generate_vs_metadata(
            embedding_model=request.embedding_model,
            chunk_size=request.chunk_size or 0,
            chunk_overlap=request.chunk_overlap or 0,
            distance_strategy=request.distance_strategy,
            index_type=request.index_type or "HNSW",
            alias=request.alias,
            description=request.description,
        )
        request.index_type = request.index_type or "HNSW"

        await populate_vs(
            db_config=db_config,
            vector_store=request,
            embed_client=get_client_embed(request.embedding_model, oci_profile),
            input_data=split_docos,
            rate_limit=rate_limit,
        )

        # Update the comment on the vector store table
        async with pool.acquire() as conn:
            await update_vs_comment(conn, request, comment_json)
            # Re-discover after creation so the cache reflects current state.
            live_stores = await discover_vector_stores(conn)
        db_config.vector_stores = list(live_stores)

        return EmbedProcessingResult(
            message="Vector store populated successfully",
            total_chunks=processing_results["total_chunks"],
            processed_files=processing_results["processed_files"],
            skipped_files=processing_results["skipped_files"],
        )
    except (ValueError, RuntimeError) as ex:
        raise HTTPException(
            status_code=500,
            detail=response_error_detail(ex, "Vector store operation failed."),
        ) from ex
    except Exception as ex:
        LOGGER.error("An exception occurred: %s", ex)
        raise HTTPException(status_code=500, detail="An unexpected error occurred during embedding.") from ex
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


@auth.post(
    "/refresh",
    description="Refresh Vector Store from OCI Bucket.",
    response_model=VectorStoreRefreshStatus,
)
async def refresh_vector_store(
    request: VectorStoreRefreshRequest,
    client: Annotated[ClientId, Header()] = "server",
) -> VectorStoreRefreshStatus:
    """Refresh an existing vector store with new/modified documents from an OCI bucket."""
    LOGGER.debug("Received refresh_vector_store - request: %s", request)
    db_config, pool = _get_client_db_config(client)

    # Resolve OCI profile — use request.auth_profile when explicitly set,
    # otherwise fall back to the client's configured profile.
    if request.auth_profile and request.auth_profile != "DEFAULT":
        oci_profile = _find_oci_profile(request.auth_profile)
    else:
        oci_profile = get_oci_profile(client)
        if not oci_profile:
            raise HTTPException(status_code=400, detail="No OCI profile configured")

    # Get existing vector store configuration
    try:
        async with pool.acquire() as conn:
            vs_config = await get_vector_store_by_alias(conn, request.vector_store_alias)
    except ValueError as ex:
        raise HTTPException(
            status_code=400,
            detail=response_error_detail(ex, "Vector store lookup failed."),
        ) from ex
    if vs_config.vector_store is None or vs_config.embedding_model is None:
        raise HTTPException(status_code=400, detail="Vector store or embedding model not configured")
    LOGGER.info("Found vector store: %s with model %s", vs_config.vector_store, vs_config.embedding_model)

    # Get current bucket objects with metadata
    current_objects = await asyncio.to_thread(get_bucket_objects_with_metadata, request.bucket_name, oci_profile)

    if not current_objects:
        return VectorStoreRefreshStatus(
            status="completed",
            message=f"No supported files found in bucket {request.bucket_name}",
            processed_files=0,
            new_files=0,
            updated_files=0,
            total_chunks=0,
        )

    # Get previously processed objects metadata
    async with pool.acquire() as conn:
        processed_objects = await get_processed_objects_metadata(conn, vs_config.vector_store)
    LOGGER.info("Found %d previously processed objects", len(processed_objects))

    # Detect changes
    new_objects, modified_objects = detect_changed_objects(current_objects, processed_objects)
    changed_objects = new_objects + modified_objects

    if not changed_objects:
        async with pool.acquire() as conn:
            total_chunks_in_store = await get_total_chunks_count(conn, vs_config.vector_store)

        return VectorStoreRefreshStatus(
            status="completed",
            message="No new or modified files to process",
            processed_files=0,
            new_files=0,
            updated_files=0,
            total_chunks=0,
            total_chunks_in_store=total_chunks_in_store,
        )

    try:
        # Refresh the vector store
        result = await refresh_vector_store_from_bucket(
            vector_store_config=vs_config,
            bucket_name=request.bucket_name,
            bucket_objects=changed_objects,
            db_config=db_config,
            embed_client=get_client_embed(vs_config.embedding_model, oci_profile),
            oci_profile=oci_profile,
            rate_limit=request.rate_limit or 0,
            modified_objects=modified_objects if modified_objects else None,
            parsing_mode=request.parsing_mode or "fast",
        )
    except ValueError as ex:
        raise HTTPException(
            status_code=400,
            detail=response_error_detail(ex, "Vector store refresh failed."),
        ) from ex
    except Exception as ex:
        LOGGER.error("Unexpected error in refresh_vector_store: %s", ex)
        raise HTTPException(status_code=500, detail="An unexpected error occurred during refresh.") from ex

    # Get total chunks after refresh
    async with pool.acquire() as conn:
        total_chunks_in_store = await get_total_chunks_count(conn, vs_config.vector_store)

    return VectorStoreRefreshStatus(
        status="completed",
        message=result.get("message", "Vector store refreshed successfully"),
        processed_files=result.get("processed_files", 0),
        new_files=result.get("new_files", 0),
        updated_files=result.get("updated_files", 0),
        total_chunks=result.get("total_chunks", 0),
        total_chunks_in_store=total_chunks_in_store,
        errors=result.get("errors", []),
    )
