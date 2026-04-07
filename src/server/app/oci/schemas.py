"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models and dataclasses for OCI profile configuration.
"""
# spell-checker: ignore genai

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

OciAuthType = Literal[
    "api_key",
    "instance_principal",
    "oke_workload_identity",
    "resource_principal",
    "security_token",
]


class OciSensitive(BaseModel):
    """Sensitive OCI profile fields excluded from default API responses."""

    fingerprint: Optional[str] = None
    key_content: Optional[str] = None
    pass_phrase: Optional[str] = None
    security_token_file: Optional[str] = None


class OciProfileConfig(OciSensitive):
    """OCI Profile configurations."""

    auth_profile: str
    user: Optional[str] = None
    authentication: OciAuthType = "api_key"
    tenancy: Optional[str] = None
    region: Optional[str] = None
    key_file: Optional[str] = None
    genai_compartment_id: Optional[str] = None
    genai_region: Optional[str] = None
    log_requests: Optional[bool] = False
    additional_user_agent: Optional[str] = ""
    namespace: Optional[str] = Field(
        default=None, description="Object Store Namespace", json_schema_extra={"readOnly": True}
    )
    usable: Optional[bool] = False
    server_managed: bool = Field(default=False, exclude=True)


class OciProfileUpdate(OciSensitive):
    """Fields allowed in an OCI profile update (all optional)."""

    @model_validator(mode="before")
    @classmethod
    def empty_strings_to_none(cls, data: Any) -> Any:
        """Convert empty strings to None to prevent phantom diffs."""
        if isinstance(data, dict):
            return {k: None if v == "" else v for k, v in data.items()}
        return data

    user: Optional[str] = None
    authentication: Optional[OciAuthType] = None
    tenancy: Optional[str] = None
    region: Optional[str] = None
    genai_compartment_id: Optional[str] = None
    genai_region: Optional[str] = None
    log_requests: Optional[bool] = None
    additional_user_agent: Optional[str] = None
