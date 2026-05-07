"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI Object Storage bucket operations for vector store refresh workflows.
"""

import logging
import os

import oci.identity
import oci.object_storage
import oci.pagination

from .client import init_client
from .schemas import OciProfileConfig

LOGGER = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".html", ".md", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".docx", ".pptx", ".xlsx"}


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


def get_bucket_object_names(bucket_name: str, profile: OciProfileConfig) -> list[str]:
    """Retrieve every object name from a bucket, aggregated across pages.

    ``list_objects`` returns one OCI page per call and the default page
    size truncates large buckets — the single-call
    ``/v1/embed/oci/store`` endpoint with ``objects`` omitted promises
    to embed every supported object in the bucket, so the listing must
    walk all pages.
    """
    client = init_client(oci.object_storage.ObjectStorageClient, profile)

    try:
        response = oci.pagination.list_call_get_all_results(
            client.list_objects,
            namespace_name=profile.namespace,
            bucket_name=bucket_name,
        )
        if response is None or response.data is None:
            return []
        return [obj.name for obj in response.data.objects]
    except oci.exceptions.ServiceError:
        LOGGER.debug("Bucket %s not found.", bucket_name)
        return []


def flatten_bucket_key(key: str) -> str:
    """Flatten a bucket object key to a unique filename by replacing path separators."""
    return key.replace("/", "_").lstrip("_")


def get_bucket_objects_with_metadata(bucket_name: str, profile: OciProfileConfig) -> list[dict]:
    """Retrieve every bucket object with metadata, aggregated across pages.

    ``list_objects`` returns one OCI page per call and the default page
    size truncates large buckets. ``/v1/embed/refresh`` relies on this
    listing to detect new and modified objects, so dropping later
    pages would treat them as if they had never existed for
    change-detection purposes.

    Returns a list of dicts with keys: name, size, etag, time_modified, md5, extension.
    Only objects with supported file extensions are included.
    """
    client = init_client(oci.object_storage.ObjectStorageClient, profile)

    objects_metadata: list[dict] = []
    try:
        response = oci.pagination.list_call_get_all_results(
            client.list_objects,
            namespace_name=profile.namespace,
            bucket_name=bucket_name,
            fields="name,size,etag,timeModified,md5",
        )
        if response is None or response.data is None:
            return objects_metadata
        objects = response.data.objects

        for obj in objects:
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
    except oci.exceptions.ServiceError:
        LOGGER.debug("Bucket %s not found.", bucket_name)

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
