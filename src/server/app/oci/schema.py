"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models and dataclasses for OCI profile configuration.
"""

from typing import Optional
from pydantic import BaseModel


class OciSensitive(BaseModel):
    """Sensitive OCI profile fields excluded from default API responses."""

    fingerprint: Optional[str] = None
    key: Optional[str] = None
    security_token_file: Optional[str] = None
    key_file: Optional[str] = None
    pass_phrase: Optional[str] = None


class OciProfileConfig(OciSensitive):
    """OCI Profile configurations."""

    auth_profile: str
    user: Optional[str] = None
    authentication: Optional[str] = "api_key"
    tenancy: Optional[str] = None
    region: Optional[str] = None
    genai_compartment_id: Optional[str] = None
    genai_region: Optional[str] = None
    log_requests: Optional[bool] = False
    additional_user_agent: Optional[str] = ""
