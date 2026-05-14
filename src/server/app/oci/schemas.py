"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models and dataclasses for OCI profile configuration.
"""
# spell-checker: ignore genai

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from server.app.core.secrets import SecretField

OciAuthType = Literal[
    "api_key",
    "instance_principal",
    "oke_workload_identity",
    "resource_principal",
    "security_token",
]

# Auth types where credentials are supplied by the deployment infrastructure
# (instance metadata / workload identity) rather than a user-managed key.
PRINCIPAL_OCI_AUTH_TYPES = frozenset({"instance_principal", "oke_workload_identity", "resource_principal"})

# Fields the DB-backed GenAI overlay speaks for. Shared by ``persist_settings``
# and the OCI/settings endpoints so the schema lives in one place.
GENAI_OVERLAY_FIELDS = frozenset({"genai_compartment_id", "genai_region"})


def genai_inference_endpoint(region: Optional[str]) -> str:
    """Construct the OCI GenAI inference endpoint URL for *region*.

    Accepts ``Optional[str]`` to match the call sites' upstream guarantees
    (``create_genai_models`` only runs when region is set; client.py gates
    the call on ``profile.genai_region``). Matches the prior inline
    f-string semantics — a stray ``None`` produces a bogus URL rather than
    raising.
    """
    return f"https://inference.generativeai.{region}.oci.oraclecloud.com"


class OciSensitive(BaseModel):
    """OCI profile fields excluded from default API responses.

    ``fingerprint`` and ``security_token_file`` remain plain ``str``.
    ``key_content`` and ``pass_phrase`` use ``SecretStr``.
    """

    fingerprint: Optional[str] = None
    key_content: SecretField = None
    pass_phrase: SecretField = None
    security_token_file: Optional[str] = None


class OciProfileConfig(OciSensitive):
    """OCI Profile configurations."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "auth_profile": "DEFAULT",
                "user": "ocid1.user.oc1..exampleuserocid",
                "authentication": "api_key",
                "tenancy": "ocid1.tenancy.oc1..exampletenancyocid",
                "region": "us-ashburn-1",
                "fingerprint": "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99",
                "key_file": "/home/opc/.oci/oci_api_key.pem",
                "genai_compartment_id": "ocid1.compartment.oc1..examplecompartocid",
                "genai_region": "us-chicago-1",
            }
        }
    }

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

    model_config = {
        "json_schema_extra": {
            "example": {
                "user": "ocid1.user.oc1..exampleuserocid",
                "region": "us-phoenix-1",
                "genai_compartment_id": "ocid1.compartment.oc1..examplecompartocid",
                "genai_region": "us-chicago-1",
            }
        }
    }

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
