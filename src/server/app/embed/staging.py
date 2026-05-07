"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

File-staging helpers for embed endpoints.
"""

import json
import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)

METADATA_FILENAME = ".file_metadata.json"


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
