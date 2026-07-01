"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

App-wide constants (leaf module — no app-level imports).
"""

SUPPORTED_EXTENSIONS = frozenset(
    {".pdf", ".html", ".md", ".txt", ".csv", ".png", ".jpg", ".jpeg", ".docx", ".pptx", ".xlsx"}
)

# Shared 503 detail used by settings-mutating endpoints when a CORE write fails.
PERSIST_FAIL_DETAIL = "Failed to persist settings"
