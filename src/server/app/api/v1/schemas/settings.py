"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Response models for server settings.
"""

from typing import Optional

from pydantic import create_model

from server.app.core.config import Settings

# Derive SettingsResponse fields from Settings so they stay in sync.
_fields = {
    name: (Optional[info.annotation], None)
    for name, info in Settings.model_fields.items()
}

SettingsResponse = create_model("SettingsResponse", **_fields)
SettingsResponse.__doc__ = "Server settings (secrets omitted by default)."
