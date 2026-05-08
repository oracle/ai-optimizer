"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared file utilities — filename sanitization and temporary directory management.
"""

import logging
import tempfile
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def safe_filename(raw: str) -> str:
    """Return the final filename component, or raise ``ValueError`` for empty / ``.`` / ``..``."""
    safe = Path(raw).name
    if not safe or safe in (".", ".."):
        raise ValueError("Invalid filename.")
    return safe


def get_temp_directory(client: str, function: str, *, unique: bool = False) -> Path:
    """Return a temporary directory scoped by *client* and *function*.

    Both arguments are sanitized via :func:`safe_filename`.  When *unique* is
    ``True`` a fresh sub-directory is created inside the scoped path (useful
    when parallel operations must not share files).
    """
    base = Path("/app/tmp") if Path("/app/tmp").is_dir() else Path(tempfile.gettempdir())
    parent = base / safe_filename(client) / safe_filename(function)
    parent.mkdir(parents=True, exist_ok=True)
    if unique:
        return Path(tempfile.mkdtemp(dir=parent))
    LOGGER.debug("Temporary directory: %s", parent)
    return parent
