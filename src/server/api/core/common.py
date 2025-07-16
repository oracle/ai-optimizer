"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from fastapi import HTTPException

from server.api.core import bootstrap

import common.schema as schema


def get_client_settings(client: schema.ClientIdType) -> schema.Settings:
    """Return schema.Settings Object based on client ID"""
    settings_objects = bootstrap.SETTINGS_OBJECTS
    client_settings = next((settings for settings in settings_objects if settings.client == client), None)
    if not client_settings:
        raise HTTPException(status_code=404, detail=f"Client: {client} not found.")
    return client_settings
