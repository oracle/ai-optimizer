"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from fastapi import APIRouter, HTTPException

from server.app.api.v1.schemas.help import HelpResponse
from server.app.core.help_text import help_dict

auth = APIRouter(prefix="/help")


@auth.get("", response_model=list[HelpResponse])
async def get_all_help():
    """Return all help text entries."""
    return [HelpResponse(key=k, text=v.strip()) for k, v in help_dict.items()]


@auth.get("/{key}", response_model=HelpResponse)
async def get_help(key: str):
    """Return help text for a specific key."""
    text = help_dict.get(key.lower())
    if text is None:
        raise HTTPException(status_code=404, detail=f"Help key '{key}' not found")
    return HelpResponse(key=key.lower(), text=text.strip())
