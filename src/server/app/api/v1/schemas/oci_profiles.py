"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for OCI profile configuration endpoints.
"""
# spell-checker: ignore genai
# pylint: disable=duplicate-code  # Pydantic schemas intentionally mirror OCI dataclass fields

from typing import Optional

from pydantic import BaseModel, Field


# --- Persistence model for aio_settings ---


class OCIConfigEntry(BaseModel):
    """Single OCI profile config as stored in the settings JSON."""

    auth_profile: str
    user: Optional[str] = None
    authentication: str = "api_key"
    security_token_file: Optional[str] = None
    fingerprint: Optional[str] = None
    tenancy: Optional[str] = None
    region: Optional[str] = None
    key: Optional[str] = None
    pass_phrase: Optional[str] = None
    genai_compartment_id: Optional[str] = None
    genai_region: Optional[str] = None
    log_requests: bool = False
    additional_user_agent: str = ""


# --- API request/response models ---


class _OCIProfileFields(BaseModel):
    """Fields shared by create and update payloads."""

    user: Optional[str] = None
    authentication: Optional[str] = None
    security_token_file: Optional[str] = None
    fingerprint: Optional[str] = None
    tenancy: Optional[str] = None
    region: Optional[str] = None
    key: Optional[str] = None
    pass_phrase: Optional[str] = None
    genai_compartment_id: Optional[str] = None
    genai_region: Optional[str] = None
    log_requests: Optional[bool] = None
    additional_user_agent: Optional[str] = None


class OCIProfileCreate(_OCIProfileFields):
    """Payload for creating a new OCI profile."""

    auth_profile: str = Field(..., pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")


class OCIProfileUpdate(_OCIProfileFields):
    """Payload for updating an existing OCI profile."""


class OCIProfileResponse(BaseModel):
    """Sanitized OCI profile returned to clients (excludes key, pass_phrase)."""

    auth_profile: str
    user: Optional[str] = None
    authentication: str = "api_key"
    security_token_file: Optional[str] = None
    fingerprint: Optional[str] = None
    tenancy: Optional[str] = None
    region: Optional[str] = None
    genai_compartment_id: Optional[str] = None
    genai_region: Optional[str] = None
    log_requests: bool = False
    additional_user_agent: str = ""
    usable: bool
