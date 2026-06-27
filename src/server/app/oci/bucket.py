"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI Object Storage bucket operations for vector store refresh workflows.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

import oci.identity
import oci.object_storage
import oci.pagination

from server.app.core.constants import SUPPORTED_EXTENSIONS

from .client import init_client
from .schemas import OciProfileConfig

LOGGER = logging.getLogger(__name__)


def filter_supported_object_names(names: Iterable[str]) -> list[str]:
    """Keep only object names whose extension is in ``SUPPORTED_EXTENSIONS``."""
    return [name for name in names if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS]


def get_compartments(profile: OciProfileConfig) -> dict[str, str]:
    """Retrieve active OCI compartments as a path-to-OCID mapping.

    Returns a dict like ``{"Tenancy / Parent / Child": "ocid1.compartment..."}``.
    """
    client = init_client(oci.identity.IdentityClient, profile)

    response = oci.pagination.list_call_get_all_results(
        client.list_compartments,
        compartment_id=profile.tenancy,
        compartment_id_in_subtree=True,
        access_level="ACCESSIBLE",
        sort_by="NAME",
        sort_order="ASC",
        lifecycle_state="ACTIVE",
    )
    if response is None:
        return {}
    compartments = response.data or []

    compartment_dict = {c.id: c for c in compartments}

    def _construct_path(compartment):
        path = []
        current = compartment
        while current:
            path.append(current.name)
            current = compartment_dict.get(current.compartment_id)
        return " / ".join(reversed(path))

    compartment_paths = {_construct_path(c): c.id for c in compartments}
    # Include the tenancy root — list_compartments never returns it
    compartment_paths["(root)"] = profile.tenancy
    LOGGER.info("Returning %d compartments", len(compartment_paths))
    return compartment_paths


def get_buckets(compartment_id: str, profile: OciProfileConfig) -> list[str]:
    """Retrieve bucket names in a compartment, excluding genai_chunk buckets."""
    client = init_client(oci.object_storage.ObjectStorageClient, profile)

    LOGGER.info("Getting buckets in compartment %s", compartment_id)
    response = oci.pagination.list_call_get_all_results(
        client.list_buckets,
        namespace_name=profile.namespace,
        compartment_id=compartment_id,
        fields=["tags"],
    )
    if response is None:
        return []
    bucket_names = []
    for bucket in response.data or []:
        freeform_tags = bucket.freeform_tags or {}
        if freeform_tags.get("genai_chunk") != "true":
            bucket_names.append(bucket.name)
    return bucket_names


def _list_all_bucket_objects(bucket_name: str, profile: OciProfileConfig, *, fields: Optional[str] = None) -> list:
    """Return every object in a bucket, aggregated across all pages.

    ``list_objects`` returns one OCI page per call and the default page size
    truncates large buckets, so callers that must see every object (whole-bucket
    embed, refresh change-detection) walk all pages. Returns an empty list when
    the bucket is missing or the response carries no data; ``fields`` selects the
    per-object attributes to populate (omit for name-only listings).
    """
    client = init_client(oci.object_storage.ObjectStorageClient, profile)
    kwargs = {"namespace_name": profile.namespace, "bucket_name": bucket_name}
    if fields:
        kwargs["fields"] = fields
    try:
        response = oci.pagination.list_call_get_all_results(client.list_objects, **kwargs)
    except oci.exceptions.ServiceError:
        LOGGER.debug("Bucket %s not found.", bucket_name)
        return []
    if response is None or response.data is None:
        return []
    return response.data.objects


def get_bucket_object_names(bucket_name: str, profile: OciProfileConfig) -> list[str]:
    """Retrieve every object name from a bucket, aggregated across pages.

    Backs the single-call ``/v1/embed/oci/store`` endpoint (with ``objects``
    omitted), which promises to embed every supported object in the bucket.
    """
    return [obj.name for obj in _list_all_bucket_objects(bucket_name, profile)]


def flatten_bucket_key(key: str) -> str:
    """Flatten a bucket object key to a unique filename by replacing path separators."""
    return key.replace("/", "_").lstrip("_")


def get_bucket_objects_with_metadata(bucket_name: str, profile: OciProfileConfig) -> list[dict]:
    """Retrieve every bucket object with metadata, aggregated across pages.

    Backs ``/v1/embed/refresh`` change-detection. Returns a list of dicts with
    keys: name, size, etag, time_modified, md5, extension. Only objects with
    supported file extensions are included.
    """
    objects_metadata: list[dict] = []
    for obj in _list_all_bucket_objects(bucket_name, profile, fields="name,size,etag,timeModified,md5"):
        _, ext = os.path.splitext(obj.name.lower())
        if ext in SUPPORTED_EXTENSIONS:
            objects_metadata.append(
                {
                    "name": obj.name,
                    "size": obj.size,
                    "etag": obj.etag,
                    "time_modified": obj.time_modified.isoformat() if obj.time_modified else None,
                    "md5": obj.md5,
                    "extension": ext[1:],
                }
            )

    LOGGER.info("Retrieved %d objects with metadata from bucket %s", len(objects_metadata), bucket_name)
    return objects_metadata


def detect_changed_objects(
    current_objects: list[dict],
    processed_objects: dict,
) -> tuple[list[dict], list[dict]]:
    """Detect new and modified objects by comparing current bucket state with processed metadata.

    Returns:
        ``(new_objects, modified_objects)``
    """
    new_objects: list[dict] = []
    modified_objects: list[dict] = []

    for obj in current_objects:
        obj_name = flatten_bucket_key(obj["name"])

        if obj_name not in processed_objects:
            new_objects.append(obj)
        else:
            last_processed = processed_objects[obj_name]

            # If old format (no etag), skip — assume unchanged
            if last_processed.get("etag") is None and last_processed.get("time_modified") is None:
                LOGGER.debug("Skipping %s - found in old metadata format (assumed unchanged)", obj_name)
                continue

            if obj["etag"] != last_processed.get("etag") or obj["time_modified"] != last_processed.get("time_modified"):
                modified_objects.append(obj)

    LOGGER.info("Found %d new objects and %d modified objects", len(new_objects), len(modified_objects))
    return new_objects, modified_objects


async def download_bucket_objects_to_dir(
    temp_directory,
    profile: OciProfileConfig,
    bucket_name: str,
    object_names: list[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Download *object_names* from *bucket_name* into *temp_directory*.

    Caller MUST already hold ``_client_lock`` for the relevant client —
    this helper has no lock semantics so it can be reused from
    ``oci_download_objects`` (which acquires the lock itself) and from
    the single-call ``/v1/embed/oci/store`` endpoint (which holds the
    lock across download + claim + submit).

    Returns ``(downloaded_basenames, failures)``. ``downloaded_basenames``
    is the list of local basenames that were written (one entry per
    successful key — colliding flattened keys produce duplicate
    basenames, since each input key was honored by a sequential
    last-writer-wins write). ``failures`` is a list of
    ``(object_name, error_message)`` tuples for keys that raised
    during download. Two-step callers can ignore the failures and
    return only the basenames; callers that need all-or-nothing
    semantics (single-call OCI embed) must check ``failures`` and
    abort before downstream consumers see a partial corpus.

    ``download_object`` is a synchronous OCI SDK call (streams the
    whole object before returning); offload via ``asyncio.to_thread``
    so the server event loop stays responsive and the embed-job
    heartbeat doesn't starve under long downloads.

    Group by ``flatten_bucket_key`` destination: two object keys like
    ``a/b.txt`` and ``a_b.txt`` both target the same local path, and
    concurrent ``open(..., "wb")`` would interleave or truncate
    writes, corrupting the file. Within a destination group we run
    sequentially (last writer wins, matching the pre-parallel loop's
    behavior); across groups we run concurrently for the common
    no-collision case.
    """
    groups: dict[str, list[str]] = {}
    for object_name in object_names:
        groups.setdefault(flatten_bucket_key(object_name), []).append(object_name)

    async def _download_destination(names: list[str]) -> list[tuple[str, str | BaseException]]:
        results: list[tuple[str, str | BaseException]] = []
        for name in names:
            try:
                path = await asyncio.to_thread(
                    download_object, str(temp_directory), name, bucket_name, profile,
                )
                results.append((name, path))
            except Exception as ex:  # caller decides what to do with the failure
                results.append((name, ex))
        return results

    group_results = await asyncio.gather(
        *(_download_destination(names) for names in groups.values()),
    )

    downloaded: list[str] = []
    failures: list[tuple[str, str]] = []
    for results in group_results:
        for object_name, result in results:
            if isinstance(result, BaseException):
                LOGGER.warning("Failed to download %s: %s", object_name, result)
                failures.append((object_name, f"{type(result).__name__}: {result}"))
            else:
                downloaded.append(os.path.basename(result))
    return downloaded, failures


def download_object(
    directory: str,
    object_name: str,
    bucket_name: str,
    profile: OciProfileConfig,
) -> str:
    """Download an object from OCI Object Storage.

    Returns the full local file path.
    """
    client = init_client(oci.object_storage.ObjectStorageClient, profile)

    file_name = flatten_bucket_key(object_name)
    file_path = os.path.join(directory, file_name)

    response = client.get_object(
        namespace_name=profile.namespace,
        bucket_name=bucket_name,
        object_name=object_name,
    )
    if response is None or response.data is None:
        msg = f"No data returned for object {object_name} in bucket {bucket_name}"
        raise ValueError(msg)
    with open(file_path, "wb") as f:
        for content in response.data.raw.stream(1024 * 1024, decode_content=False):
            f.write(content)

    file_size = os.path.getsize(file_path)
    LOGGER.info("Downloaded %s to %s (%i bytes)", file_name, file_path, file_size)
    return file_path
