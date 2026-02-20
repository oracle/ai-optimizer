"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Response models for settings endpoint.
"""

from server.app.core.settings import SettingsBase


class SettingsResponse(SettingsBase):
    """Response for the settings endpoint."""
