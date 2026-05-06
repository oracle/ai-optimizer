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
import re
import shutil
import tempfile
import zipfile
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import urlparse

import oracledb
from fastapi import APIRouter, Body, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import HttpUrl

from server.app.api.v1.endpoints.oci import _find_oci_profile
from server.app.api.v1.schemas.chat import MessageResponse
from server.app.api.v1.schemas.common import ClientId
from server.app.api.v1.schemas.embed import (
    EmbedJobAccepted,
    EmbedJobInfo,
    EmbedJobStage,
    EmbedProcessingResult,
    SqlStoreRequest,
    VectorStoreRefreshRequest,
    VectorStoreRefreshStatus,
)
from server.app.core.error_detail import response_error_detail
from server.app.core.file_utils import get_temp_directory, safe_filename
from server.app.core.settings import _settings_lock, resolve_client, settings
from server.app.database.config import get_client_db_config as _resolve_db_config
from server.app.database.config import get_core_pool, get_database_settings
from server.app.database.registry import discover_vector_stores, drop_vector_store
from server.app.database.sql import execute_sql
from server.app.embed.document import load_and_split_documents
from server.app.embed.jobs import (
    EmbedJobStoreUnavailable,
    JobHandle,
    JobSubmission,
    get_embed_job_manager,
)
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


# ``run_sql_query`` writes its output as ``_sqlsrc_<uuid4>.csv`` in
# the shared embedding directory (see
# :func:`server.app.embed.utils._run_sql_query_sync`). The literal
# ``_sqlsrc_`` prefix is the explicit marker the restore path uses
# to identify SQL-generated files: a user-uploaded CSV whose
# basename happens to be a UUID would otherwise be dropped as
# collateral damage of the SQL-detection branch.
#
# These files are *ephemeral*: the Streamlit retry path always
# re-runs ``/embed/sql/store`` before retrying ``POST /embed/``, and
# each call allocates a fresh UUID. Restoring an old SQL CSV would
# make the next embed claim *both* the restored CSV and the
# newly-generated one — embedding the SQL query results twice.
# User-uploaded files use deterministic, source-derived names so the
# existing same-name skip in the restore loop dedupes them naturally;
# only marker-prefixed SQL outputs accumulate across retries, so
# that prefix is what the restore drops.
_SQL_GENERATED_CSV_RE = re.compile(
    r"^_sqlsrc_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.csv$",
    re.IGNORECASE,
)


async def _sweep_sql_scratch_files(client: str) -> None:
    """Drop ``_sqlsrc_<uuid>.csv`` files from the client's shared embedding dir.

    Called on pre-claim retry-able failures from ``POST /v1/embed/``
    (503 from the CORE-availability guard, 400 from missing fields,
    etc.). The Streamlit retry path always re-runs
    ``/embed/sql/store`` before the next ``POST /embed/``, which
    allocates a fresh UUID. Leaving the previous run's CSV in place
    would let the next embed claim both files and embed the query
    results twice.

    Only marker-prefixed files are dropped — user uploads keep
    deterministic, source-derived names so the same-name skip in
    the post-claim restore path dedupes them naturally.

    Acquires ``_client_lock`` so a concurrent same-client
    ``/embed/sql/store`` cannot land a new ``_sqlsrc_*.csv`` mid-
    sweep.
    """
    shared_dir = get_temp_directory(client, "embedding")

    def _sweep() -> None:
        if not shared_dir.exists():
            return
        for item in shared_dir.iterdir():
            if item.is_file() and _SQL_GENERATED_CSV_RE.match(item.name):
                try:
                    item.unlink()
                except OSError as ex:
                    LOGGER.warning(
                        "Could not drop stale SQL scratch file %s: %s",
                        item, ex,
                    )

    async with _client_lock(client):
        await asyncio.to_thread(_sweep)


async def _restore_claimed_files_to_shared_under_lock(client: str, work_dir: Path) -> None:
    """Move files in *work_dir* back to the shared client embedding dir.

    Used on retry-able submission failures (the 503 path) so the
    client can simply retry the POST without re-uploading the entire
    corpus. Caller MUST already hold ``_client_lock(client)`` —
    ``asyncio.Lock`` is non-reentrant, so re-acquiring would deadlock,
    and the whole point of this helper is to run while the outer
    handler still holds the lock from the original ``_prepare_work_dir``
    claim. Without that hand-off, a concurrent ``store_local_file``
    could land different-named files in shared between claim and
    submission failure; this loop only skips same-name conflicts, so
    the merged result would let the next embed claim a mix of stale
    and newly uploaded files. The ``work_dir`` is rmtree'd at the end
    regardless of whether the move succeeded.

    SQL-generated UUID CSVs are dropped rather than restored — see
    :data:`_SQL_GENERATED_CSV_RE` for why.
    """
    if not work_dir.exists():
        return
    shared_dir = get_temp_directory(client, "embedding")

    def _move_back() -> None:
        for item in work_dir.iterdir():
            if item.is_file():
                if _SQL_GENERATED_CSV_RE.match(item.name):
                    LOGGER.debug(
                        "Dropping SQL-generated CSV %s on restore — retry "
                        "will regenerate via /embed/sql/store",
                        item.name,
                    )
                    continue
                target = shared_dir / item.name
                # If a same-name file was uploaded after this job
                # claimed its corpus, leave the newer one in place
                # rather than clobber it. The user can resolve the
                # conflict on the next retry.
                if target.exists():
                    LOGGER.warning(
                        "Skipping restore of %s — shared dir already has %s",
                        item, target,
                    )
                    continue
                shutil.move(str(item), str(target))

    try:
        await asyncio.to_thread(_move_back)
    except OSError as ex:
        LOGGER.warning(
            "Could not restore claimed files for client %s from %s: %s",
            client, work_dir, ex,
        )
    shutil.rmtree(work_dir, ignore_errors=True)


_pending_workdir_cleanups: set[asyncio.Task] = set()


def _tear_down_post_submit_request(submission: JobSubmission, work_dir: Path) -> None:
    """Tear down a submission whose request failed after ``manager.submit``
    returned but before the 202 response was sent.

    Two correctness concerns interact:

    * ``Task.cancel()`` on a task that has not yet received its first
      event-loop step throws ``CancelledError`` before any user code
      runs — so ``_run``'s outer ``finally`` never pops ``_tasks``
      and the pipeline body's ``finally`` never rmtrees ``work_dir``.
      Without explicit cleanup the heartbeat would refresh a stranded
      QUEUED row and the corpus would leak on disk.
    * ``Task.cancel()`` on a task that *has* started only requests
      cancellation; work already running inside ``asyncio.to_thread``
      keeps executing in a worker thread. Yanking ``work_dir`` while
      that thread is mid-read or mid-write would corrupt a partially-
      populated vector store.

    The shape that satisfies both: pop ``_tasks`` eagerly (heartbeat
    stops refreshing immediately), but defer the rmtree to a
    fire-and-forget cleanup task that awaits ``submission.task``
    first. If the task ran its own pipeline-finally rmtree, the
    deferred one is a no-op via ``ignore_errors=True``.
    """
    submission.task.cancel()
    get_embed_job_manager().discard_local_task(submission.job_id)

    async def _await_then_rmtree() -> None:
        with contextlib.suppress(BaseException):
            await submission.task
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    cleanup_task = asyncio.create_task(_await_then_rmtree())
    # Pin to a module-level set so the task isn't GC'd before
    # completing (asyncio holds only a weak reference once
    # ``create_task`` returns).
    _pending_workdir_cleanups.add(cleanup_task)
    cleanup_task.add_done_callback(_pending_workdir_cleanups.discard)


async def _cleanup_failed_submission(
    submission: Optional[JobSubmission],
    work_dir: Path,
    client: str,
    *,
    can_restore: bool,
) -> None:
    """Run the right teardown for a failed ``split_embed`` attempt.

    *can_restore* gates the post-claim restore-vs-rmtree decision:
    True for retryable 503 paths (client retries with the same
    corpus); False for non-retryable failures (cancellation,
    programmer errors). Once submission has succeeded the task owns
    ``work_dir`` regardless, so that branch always goes through
    :func:`_tear_down_post_submit_request`.
    """
    if submission is not None:
        _tear_down_post_submit_request(submission, work_dir)
    elif can_restore:
        await _restore_claimed_files_to_shared_under_lock(client, work_dir)
    else:
        shutil.rmtree(work_dir, ignore_errors=True)


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

    # Serialise shared-dir writes against a concurrent /embed/ retry
    # restore — see ``_restore_claimed_files_to_shared_under_lock``.
    async with _client_lock(client):
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
    request: list[HttpUrl] = Body(
        ...,
        examples=[
            [
                "https://docs.oracle.com/en/cloud/paas/autonomous-database/index.html",
                "https://example.com/whitepaper.pdf",
            ]
        ],
    ),
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

    # Serialise shared-dir writes against a concurrent /embed/ retry
    # restore — see ``_restore_claimed_files_to_shared_under_lock``.
    async with _client_lock(client):
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


async def _run_split_embed_pipeline(
    handle: JobHandle,
    request: VectorStoreConfig,
    rate_limit: int,
    client: str,
    work_dir: Path,
    files: list[Path],
    file_metadata: Optional[dict],
    db_config,
) -> EmbedProcessingResult:
    """Background body of the split-and-embed pipeline.

    Files are claimed *before* the job is submitted (see the POST handler),
    so this body operates on a stable work_dir / files snapshot — later
    uploads to the shared client directory remain separate from this
    job's corpus. The body is responsible for parse → chunk → embed →
    MERGE → HNSW build → vector-store cache refresh, plus cleaning up
    the work_dir on every exit path — including failures of the
    precondition lookups below, which is why ``try`` wraps them too.

    *db_config* is the snapshot captured at submission time. The
    pipeline must NOT re-resolve from settings: a concurrent edit to
    the client's database settings between POST 202 and pipeline
    execution could otherwise use a different database than the one
    associated with this submission.
    OCI profile is still re-resolved (it has no equivalent
    submission-time guarantee on this code path).
    """
    try:
        # The POST handler validated these are non-None; the static
        # checker only sees ``Optional[...]`` though, so re-narrow here.
        # ``assert`` rather than re-raising HTTPException because the
        # precondition is structural (a request that reached the
        # background body without these fields is a programming error,
        # not user input we want to surface as 4xx).
        assert request.embedding_model is not None, "embedding_model required"
        assert request.distance_strategy is not None, "distance_strategy required"
        embedding_model = request.embedding_model
        distance_strategy = request.distance_strategy

        # Use the captured pool from submission time. If it has been
        # closed since (config rotation, pool rebuild), the next
        # ``acquire`` will raise ``oracledb.Error`` and the outer
        # except converts it to a terminal-state job failure — the
        # right outcome, since the submission-time database snapshot
        # no longer corresponds to a live database. OCI profile is re-resolved
        # because it has no equivalent submission-time capture.
        pool = db_config.pool
        oci_profile = get_oci_profile(client)

        await handle.set_progress(
            EmbedJobStage.SPLITTING,
            message="Parsing and chunking documents.",
        )
        split_docos, _, processing_results = await asyncio.to_thread(
            load_and_split_documents,
            files,
            f"{embedding_model.provider}/{embedding_model.id}",
            request.chunk_size or 0,
            request.chunk_overlap or 0,
            write_json=False,
            output_dir=None,
            file_metadata=file_metadata,
            parsing_mode=request.parsing_mode or "fast",
        )

        # Generate the vector store table name and comment
        request.vector_store, comment_json = generate_vs_metadata(
            embedding_model=embedding_model,
            chunk_size=request.chunk_size or 0,
            chunk_overlap=request.chunk_overlap or 0,
            distance_strategy=distance_strategy,
            index_type=request.index_type or "HNSW",
            alias=request.alias,
            description=request.description,
        )
        request.index_type = request.index_type or "HNSW"

        await handle.set_progress(
            EmbedJobStage.EMBEDDING,
            message="Embedding chunks and writing to the vector store.",
            total_chunks=processing_results.get("total_chunks"),
        )
        await populate_vs(
            db_config=db_config,
            vector_store=request,
            embed_client=get_client_embed(embedding_model, oci_profile),
            input_data=split_docos,
            rate_limit=rate_limit,
        )

        await handle.set_progress(
            EmbedJobStage.FINALIZING,
            message="Updating vector store metadata.",
            total_chunks=processing_results.get("total_chunks"),
        )
        # Update the comment on the vector store table
        async with pool.acquire() as conn:
            await update_vs_comment(conn, request, comment_json)
            # Re-discover after creation so the cache reflects current state.
            live_stores = await discover_vector_stores(conn)
        refreshed = list(live_stores)
        # Keep the snapshot consistent for any downstream code in this
        # function that reads it; the snapshot is private to this job.
        db_config.vector_stores = refreshed
        # The snapshot is what *this* pipeline runs against, but the
        # /v1/settings endpoint and the Streamlit selectors read
        # ``settings.database_configs`` — the live registry. Updating
        # only the snapshot leaves the UI showing no newly created
        # store until an unrelated rediscovery / restart updates the
        # live config. Look up the matching live entry by alias and
        # refresh its ``vector_stores`` too — but only if the live
        # config still represents the *same* pool we discovered
        # against. An admin-driven config update / pool rebuild
        # rotates ``live.pool`` to a fresh ``AsyncConnectionPool`` for
        # a different (possibly different-DB) connection, while we
        # still hold the original captured pool here. Publishing the
        # captured-pool discovery into the rotated config would put
        # tables that don't exist in the new DB into the cache.
        # On mismatch (rotation, alias removed, alias reused for a
        # different pool) skip silently — the next discovery against
        # whatever ``live.pool`` is now will catch up.
        live_cfg = get_database_settings(settings.database_configs, db_config.alias)
        if live_cfg is not None and live_cfg.pool is pool:
            live_cfg.vector_stores = refreshed

        return EmbedProcessingResult(
            message="Vector store populated successfully",
            total_chunks=processing_results["total_chunks"],
            processed_files=processing_results["processed_files"],
            skipped_files=processing_results["skipped_files"],
        )
    except HTTPException:
        # Pipeline-authored 4xx/5xx — manager records the detail.
        raise
    except (ValueError, RuntimeError) as ex:
        raise HTTPException(
            status_code=500,
            detail=response_error_detail(ex, "Vector store operation failed."),
        ) from ex
    except Exception as ex:
        LOGGER.error("An exception occurred: %s", ex)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during embedding.",
        ) from ex
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@auth.post(
    "/",
    description=(
        "Schedule split-and-embed; returns 202 with a job ID. Poll "
        "GET /v1/embed/jobs/{job_id} for terminal state. Job state is "
        "persisted in the CORE database (aio_embed_jobs) so any "
        "replica can serve the status endpoint, but the pipeline body "
        "runs on the pod that accepted the POST — uploads and embed "
        "submissions for the same client must therefore be routed to "
        "the same pod (sticky routing or single-replica) until the "
        "shared file storage is moved off per-pod emptyDir."
    ),
    status_code=202,
    response_model=EmbedJobAccepted,
)
async def split_embed(
    request: VectorStoreConfig,
    rate_limit: int = 0,
    client: Annotated[ClientId, Header()] = "server",
) -> EmbedJobAccepted:
    """Claim the corpus files synchronously, then schedule the pipeline.

    Two correctness obligations live in this handler rather than the
    background body:

    1. The split-and-embed pipeline is too long to hold an HTTP
       connection open across (parse → chunk → embed → MERGE → HNSW
       build routinely exceeds LB / nginx idle timeouts on cold
       embedding models or large corpora) — so the heavy stages run
       off-request and the response is 202 + job id.
    2. Files must be claimed under the per-client lock *before* the
       202 returns. Otherwise an upload that races between the
       response and the background task acquiring the same lock would
       silently get embedded into this job — the user thinks they are
       submitting one corpus but the server processes a superset.
    """
    LOGGER.debug("Received split_embed - rate_limit: %i; request: %s", rate_limit, request)
    # All four pre-claim guards below can raise before
    # ``_prepare_work_dir`` runs, so the post-claim restore path
    # never executes. With SQL sources, ``/embed/sql/store`` has
    # already left a unique ``_sqlsrc_<uuid>.csv`` in the shared
    # directory; the Streamlit retry re-runs ``/embed/sql/store``
    # before the next ``POST /embed/`` and allocates a fresh UUID.
    # Without sweeping, the next embed would claim both the old
    # and the new ``_sqlsrc_*.csv`` and embed the query results
    # twice. ``_sweep_sql_scratch_files`` runs under
    # ``_client_lock`` so a concurrent ``/embed/sql/store`` cannot
    # land a new scratch file mid-sweep.
    try:
        # Validate DB availability up front so an unusable client
        # gets the synchronous 503 they expect rather than a job
        # that immediately fails — same precondition the inline
        # flow enforced. The result is intentionally discarded: the
        # actual snapshot the pipeline runs against is taken
        # further down under ``_settings_lock`` to close the
        # rotation race (see comment at the snapshot site).
        _get_client_db_config(client)

        # Job state (status / progress / result) lives in the CORE
        # database so any replica can serve
        # GET /v1/embed/jobs/{job_id}. Without CORE, the in-memory
        # fallback in the jobs module would still accept the
        # submission, but a poll routed to another pod (or to this
        # same pod after CORE recovers) would 404.
        _require_core_pool()

        if not request.embedding_model or request.distance_strategy is None:
            raise HTTPException(status_code=400, detail="embedding_model and distance_strategy are required")

        # Surface OCI-profile lookup errors synchronously rather than
        # silently failing the job; the pipeline body re-resolves later.
        get_oci_profile(client)
    except HTTPException:
        await _sweep_sql_scratch_files(client)
        raise

    work_dir = get_temp_directory(client, "embedding", unique=True)

    # Claim files now, on the request thread, so a follow-up upload to
    # the shared client embedding directory cannot land in this job's
    # corpus. Empty corpus → synchronous 404 (matches the inline-flow
    # contract that "no files" is a client error, not a job error).
    #
    # The lock is held all the way through ``manager.submit``: if it
    # were released after ``_prepare_work_dir`` and re-acquired only
    # for the 503-path restoration, a concurrent same-client upload
    # could land different-named files in shared during the unlocked
    # window. The restore loop only skips same-name conflicts, so the
    # merged shared dir would let the *next* embed request claim a
    # mix of stale and newly uploaded files. Holding the lock through
    # submit closes that race; once submit returns successfully the
    # corpus is owned by the background task's work_dir and concurrent
    # uploads can resume immediately.
    async with _client_lock(client):
        files = await asyncio.to_thread(
            _prepare_work_dir,
            get_temp_directory(client, "embedding"),
            work_dir,
            client,
        )
        LOGGER.info("Processing Files: %s", files)

        # ``submission`` flips from None to a JobSubmission only after
        # ``manager.submit`` returns. The except branches use it to
        # decide between corpus-restore (no task yet) and task-teardown
        # (task owns work_dir).
        submission: Optional[JobSubmission] = None
        try:
            file_metadata = await asyncio.to_thread(_load_file_metadata, work_dir)

            manager = get_embed_job_manager()
            # Hold ``_settings_lock`` across both the DB snapshot and
            # the submit so a concurrent CORE rotation cannot close
            # ``captured_pool`` between snapshot and INSERT. The
            # rotation handler holds the same lock across its active-
            # job check + ``close_pool``, so the two paths are mutually
            # exclusive. ``model_copy`` gives the snapshot its own
            # attribute storage so post-submit edits to the live
            # ``DatabaseConfig`` cannot retarget the in-flight job.
            async with _settings_lock:
                _live_db_config, captured_pool = _get_client_db_config(client)
                db_config = _live_db_config.model_copy()
                db_config.pool = captured_pool

                async def _factory(handle: JobHandle) -> EmbedProcessingResult:
                    return await _run_split_embed_pipeline(
                        handle,
                        request,
                        rate_limit,
                        client,
                        work_dir,
                        files,
                        file_metadata,
                        db_config,
                    )

                submission = await manager.submit(
                    client=client,
                    target_db=db_config.alias,
                    coro_factory=_factory,
                )
        except (oracledb.Error, EmbedJobStoreUnavailable, TimeoutError) as ex:
            # CORE-side blip during the INSERT. submission is None
            # by construction here (the error came from inside
            # ``manager.submit`` before it returned), so the cleanup
            # restores the corpus for the documented retry.
            await _cleanup_failed_submission(submission, work_dir, client, can_restore=True)
            LOGGER.warning("CORE submission failed for embed job: %s", ex)
            raise HTTPException(status_code=503, detail=_CORE_UNAVAILABLE_DETAIL) from ex
        except HTTPException as ex:
            # 503 from the under-lock DB re-snapshot is retryable
            # (admin restores the DB, client retries with the same
            # corpus); 4xx are not.
            await _cleanup_failed_submission(
                submission, work_dir, client,
                can_restore=ex.status_code == 503,
            )
            raise
        except BaseException:
            # Cancellation / programmer error. Always non-retryable.
            await _cleanup_failed_submission(submission, work_dir, client, can_restore=False)
            raise

    # All ``except`` clauses re-raise, so reaching here means
    # ``submission`` was assigned. ``assert`` is for the type checker.
    assert submission is not None
    return EmbedJobAccepted(
        job_id=submission.job_id,
        status=submission.status,
        location=f"/v1/embed/jobs/{submission.job_id}",
    )


# ---------------------------------------------------------------------------
# GET /jobs and /jobs/{job_id}
#
# These coexist with the earlier-registered ``GET /{vs}/files`` route
# without ambiguity because ``/files`` is a literal second segment
# while ``{job_id}`` is always a uuid hex — the two never overlap. A
# GET /jobs (single segment) only matches the list endpoint here.
# ---------------------------------------------------------------------------


_CORE_UNAVAILABLE_DETAIL = (
    "Embed job status is temporarily unavailable; please retry shortly."
)


def _require_core_pool() -> None:
    """Refuse job-state reads/writes when CORE is unavailable.

    Reads must surface 503 instead of falling back to the per-process
    in-memory store: a real job already persisted in ``aio_embed_jobs``
    would otherwise look like 'not found' on a sibling replica or
    after a CORE outage, and clients would stop polling.
    """
    if get_core_pool() is None:
        raise HTTPException(status_code=503, detail=_CORE_UNAVAILABLE_DETAIL)


@auth.get(
    "/jobs",
    description="List background embed jobs scoped to the requesting client.",
    response_model=list[EmbedJobInfo],
)
async def list_embed_jobs(
    client: Annotated[ClientId, Header()] = "server",
) -> list[EmbedJobInfo]:
    """Return every (still-tracked) embed job belonging to *client*."""
    _require_core_pool()
    manager = get_embed_job_manager()
    try:
        jobs = await manager.list_for_client(client)
    except (oracledb.Error, EmbedJobStoreUnavailable, TimeoutError) as ex:
        # Either the DB is momentarily unreachable (``oracledb.Error``,
        # built-in ``TimeoutError`` from a pool acquire / SELECT
        # deadline) or the pool was cleared between
        # ``_require_core_pool`` and the store read (TOCTOU race;
        # ``_store_list_for_client`` raises rather than falling back
        # to the per-process in-memory store, which production never
        # writes to). Surface 503 — the documented retry signal —
        # rather than 500 so polling clients back off instead of
        # aborting.
        LOGGER.warning("CORE read failed for embed-job list (client=%s): %s", client, ex)
        raise HTTPException(status_code=503, detail=_CORE_UNAVAILABLE_DETAIL) from ex
    return [j.to_info() for j in jobs]


@auth.get(
    "/jobs/{job_id}",
    description="Get the status and (on completion) result of an embed job.",
    response_model=EmbedJobInfo,
)
async def get_embed_job(
    job_id: str,
    client: Annotated[ClientId, Header()] = "server",
) -> EmbedJobInfo:
    """Return current job state. Jobs are scoped per Client header.

    A 404 means either the id was never issued or the job has been
    evicted — clients should not retry a 404 indefinitely. A 503
    means CORE is temporarily unavailable (either the pool is gone
    or a read failed mid-flight); clients should back off and retry
    rather than treat the job as gone.
    """
    _require_core_pool()
    manager = get_embed_job_manager()
    try:
        job = await manager.get(client, job_id)
    except (oracledb.Error, EmbedJobStoreUnavailable, TimeoutError) as ex:
        # Same triple-source 503 contract as the list endpoint:
        # ``oracledb.Error`` is a transient DB outage; the built-in
        # ``TimeoutError`` is what ``oracledb`` async pools raise on
        # acquire / SELECT deadlines (does NOT inherit from
        # ``oracledb.Error``); ``EmbedJobStoreUnavailable`` is the
        # TOCTOU race where the pool was cleared between the endpoint
        # guard and ``_store_get``. The Streamlit poller only retries
        # 503s — converting all three avoids a transient timeout
        # aborting polling for a job that may still be running.
        LOGGER.warning("CORE read failed for embed job %s: %s", job_id, ex)
        raise HTTPException(status_code=503, detail=_CORE_UNAVAILABLE_DETAIL) from ex
    if job is None:
        raise HTTPException(status_code=404, detail=f"Embed job not found: {job_id}")
    return job.to_info()


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
