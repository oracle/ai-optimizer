"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("ai-optimizer")
except PackageNotFoundError:
    __version__ = "0.0.0"
