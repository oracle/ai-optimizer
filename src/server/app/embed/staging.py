"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

File-staging helpers for embed endpoints — ZIP extraction, atomic file
promotion, SQL-scratch cleanup, and shared/work-dir corpus moves.
"""
# spell-checker:ignore ENOSPC EROFS sqlsrc zipextract rmtree litellm

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
from pathlib import Path

from fastapi import HTTPException

from server.app.core.client_locks import _client_lock

LOGGER = logging.getLogger(__name__)

METADATA_FILENAME = ".file_metadata.json"

# ZIP extraction limits
_ZIP_MAX_FILES = 500
_ZIP_MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB total decompressed
_ZIP_MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB per file
_ZIP_STREAM_CHUNK = 64 * 1024  # copy buffer for streaming zip extraction
_ZIP_BLOCKED_EXTENSIONS = frozenset({".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar"})


def load_file_metadata(work_dir: Path):
    """Load ``.file_metadata.json`` from *work_dir* if present, else return None."""
    metadata_path = work_dir / METADATA_FILENAME
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
                _promote_atomically(metadata, staging, dest, detail="Failed to finalize archive extraction.")
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        except (zipfile.BadZipFile, zlib.error) as ex:
            raise HTTPException(
                status_code=400,
                detail="ZIP archive is corrupt or unreadable.",
            ) from ex
    return metadata


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


async def _sweep_sql_scratch_files(client: str, shared_dir: Path) -> None:
    """Drop ``_sqlsrc_<uuid>.csv`` files from the client's shared embedding dir.

    *shared_dir* is the client's shared embedding directory, resolved by
    the caller so the temp-directory seam stays in the endpoint layer.

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


async def _restore_claimed_files_to_shared_under_lock(client: str, work_dir: Path, shared_dir: Path) -> None:
    """Move files in *work_dir* back to the shared client embedding dir.

    *shared_dir* is the client's shared embedding directory, resolved by
    the caller so the temp-directory seam stays in the endpoint layer.

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

    files = [f for f in work_dir.iterdir() if f.is_file() and f.name != METADATA_FILENAME]
    if not files:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=404,
            detail=f"Embed: Client {client} no files found in folder.",
        )
    return files
