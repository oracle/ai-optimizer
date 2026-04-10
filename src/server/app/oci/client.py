"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Reusable OCI client factory.
"""
# spell-checker: ignore genai

import logging
from typing import Callable, Optional, TypeVar

import oci.auth.signers
import oci.generative_ai_inference
import oci.retry
import oci.signer

from .schemas import OciProfileConfig

T = TypeVar("T")
LOGGER = logging.getLogger(__name__)


def get_signer(profile: OciProfileConfig) -> Optional[object]:
    """Return an OCI signer for delegation/principal auth types, else None."""
    if profile.authentication == "instance_principal":
        LOGGER.info("Creating Instance Principal signer")
        return oci.auth.signers.InstancePrincipalsSecurityTokenSigner()

    if profile.authentication == "resource_principal":
        LOGGER.info("Creating Resource Principal signer")
        return oci.auth.signers.get_resource_principals_signer()

    if profile.authentication == "oke_workload_identity":
        LOGGER.info("Creating OKE Workload Identity signer")
        return oci.auth.signers.get_oke_workload_identity_resource_principal_signer()

    return None


def init_client(client_type: Callable[..., T], profile: OciProfileConfig, **kwargs) -> T:
    """Create any OCI SDK client from an OciProfileConfig.

    Accepts keyword overrides (e.g. timeout) that are merged into the
    default client_kwargs.  Raises oci.exceptions.InvalidConfig on bad
    config — callers decide how to surface that.
    """
    client_kwargs = {
        "retry_strategy": oci.retry.NoneRetryStrategy(),
        "timeout": (1, 180),
    }
    client_kwargs.update(kwargs)

    # GenAI inference endpoint override
    if (
        client_type == oci.generative_ai_inference.GenerativeAiInferenceClient
        and profile.genai_compartment_id
        and profile.genai_region
    ):
        client_kwargs["service_endpoint"] = f"https://inference.generativeai.{profile.genai_region}.oci.oraclecloud.com"

    signer = get_signer(profile)

    if signer:
        return client_type(
            config={"region": profile.region},
            signer=signer,
            **client_kwargs,
        )

    if profile.authentication == "security_token" and profile.security_token_file:
        with open(profile.security_token_file, "r", encoding="utf-8") as f:
            token = f.read()
        if profile.key_file:
            private_key = oci.signer.load_private_key_from_file(profile.key_file, profile.pass_phrase)
        else:
            private_key = oci.signer.load_private_key(profile.key_content or "", profile.pass_phrase)
        sec_token_signer = oci.auth.signers.SecurityTokenSigner(token, private_key)
        return client_type(
            config={"region": profile.region},
            signer=sec_token_signer,
            **client_kwargs,
        )

    # API key (default)
    config_dict = {
        "user": profile.user,
        "fingerprint": profile.fingerprint,
        "tenancy": profile.tenancy,
        "region": profile.region,
        "pass_phrase": profile.pass_phrase,
    }
    if profile.key_content:
        config_dict["key_content"] = profile.key_content
    elif profile.key_file:
        config_dict["key_file"] = profile.key_file
    return client_type(config_dict, **client_kwargs)
