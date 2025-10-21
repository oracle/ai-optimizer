"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore litellm giskard ollama llms
# pylint: disable=unused-argument,protected-access

from typing import TYPE_CHECKING, List, Optional, Any, Tuple
import time
import json
from importlib.metadata import version as get_version
import litellm
from litellm.llms.ollama.completion.transformation import OllamaConfig
from litellm.llms.oci.chat.transformation import OCIChatConfig
from litellm.types.llms.openai import AllMessageValues
from litellm.types.utils import ModelResponse
from httpx._models import Response
import oci

from common import logging_config

logger = logging_config.logging.getLogger("patches.litellm_patch")

# Get litellm version
try:
    LITELLM_VERSION = get_version("litellm")
except Exception:
    LITELLM_VERSION = "unknown"

# Only patch if not already patched
if not getattr(OllamaConfig.transform_response, "_is_custom_patch", False):
    if TYPE_CHECKING:
        from litellm.litellm_core_utils.litellm_logging import Logging as _LiteLLMLoggingObj

        LiteLLMLoggingObj = _LiteLLMLoggingObj
    else:
        LiteLLMLoggingObj = Any

    def custom_transform_response(
        self,
        model: str,
        raw_response: Response,
        model_response: ModelResponse,
        logging_obj: LiteLLMLoggingObj,
        request_data: dict,
        messages: List[AllMessageValues],
        optional_params: dict,
        litellm_params: dict,
        encoding: str,
        api_key: Optional[str] = None,
        json_mode: Optional[bool] = None,
    ):
        """
        Custom transform response from
        .venv/lib/python3.11/site-packages/litellm/llms/ollama/completion/transformation.py
        """
        logger.info("Custom transform_response is running")
        response_json = raw_response.json()

        model_response.choices[0].finish_reason = "stop"
        model_response.choices[0].message.content = response_json["response"]

        _prompt = request_data.get("prompt", "")
        prompt_tokens = response_json.get(
            "prompt_eval_count",
            len(encoding.encode(_prompt, disallowed_special=())),
        )
        completion_tokens = response_json.get("eval_count", len(response_json.get("message", {}).get("content", "")))

        setattr(
            model_response,
            "usage",
            litellm.Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
        model_response.created = int(time.time())
        model_response.model = "ollama/" + model
        return model_response

    # Mark it to avoid double patching
    custom_transform_response._is_custom_patch = True

    # Patch it
    OllamaConfig.transform_response = custom_transform_response


# Patch OCI validate_environment to support instance principals
if not getattr(OCIChatConfig.validate_environment, "_is_custom_patch", False):
    original_validate_environment = OCIChatConfig.validate_environment

    def custom_validate_environment(
        self,
        headers: dict,
        model: str,
        messages: List[AllMessageValues],
        optional_params: dict,
        litellm_params: dict,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ) -> dict:
        """
        Custom validate_environment to support instance principals and workload identity.
        If oci_signer is present, use signer-based auth; otherwise use credential-based auth.
        """
        oci_signer = optional_params.get("oci_signer")

        # If signer is provided, use signer-based authentication (instance principals/workload identity)
        if oci_signer:
            logger.info("OCI signer detected - using signer-based authentication")
            oci_region = optional_params.get("oci_region", "us-ashburn-1")
            api_base = (
                api_base or litellm.api_base or f"https://inference.generativeai.{oci_region}.oci.oraclecloud.com"
            )

            if not api_base:
                raise Exception(
                    "Either `api_base` must be provided or `litellm.api_base` must be set. "
                    "Alternatively, you can set the `oci_region` optional parameter to use the default OCI region."
                )

            headers.update(
                {
                    "content-type": "application/json",
                    "user-agent": f"litellm/{LITELLM_VERSION}",
                }
            )

            if not messages:
                raise Exception("kwarg `messages` must be an array of messages that follow the openai chat standard")

            return headers

        # For credential-based auth, use original validation
        return original_validate_environment(
            self, headers, model, messages, optional_params, litellm_params, api_key, api_base
        )

    # Mark it to avoid double patching
    custom_validate_environment._is_custom_patch = True

    # Patch it
    OCIChatConfig.validate_environment = custom_validate_environment


# Patch OCI sign_request to support instance principals
if not getattr(OCIChatConfig.sign_request, "_is_custom_patch", False):
    original_sign_request = OCIChatConfig.sign_request

    def custom_sign_request(
        self,
        headers: dict,
        optional_params: dict,
        request_data: dict,
        api_base: str,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        stream: Optional[bool] = None,
        fake_stream: Optional[bool] = None,
    ) -> Tuple[dict, Optional[bytes]]:
        """
        Custom sign_request to support instance principals and workload identity.
        If oci_signer is present, use it for signing; otherwise use credential-based auth.
        """
        oci_signer = optional_params.get("oci_signer")

        # If signer is provided, use it for request signing
        if oci_signer:
            logger.info("Using OCI signer for request signing")

            # Prepare the request
            from urllib.parse import urlparse

            body = json.dumps(request_data).encode("utf-8")
            parsed = urlparse(api_base)
            method = str(optional_params.get("method", "POST")).upper()

            # Prepare headers with required fields for OCI signing
            prepared_headers = headers.copy()
            prepared_headers.setdefault("content-type", "application/json")
            prepared_headers.setdefault("content-length", str(len(body)))

            # Create a mock request object for OCI signing
            # Must have attributes: method, url, path_url, headers, body
            class MockRequest:
                def __init__(self, method, url, headers, body):
                    self.method = method
                    self.url = url
                    self.headers = headers
                    self.body = body
                    # path_url is the path + query string
                    parsed_url = urlparse(url)
                    self.path_url = parsed_url.path + ("?" + parsed_url.query if parsed_url.query else "")

            mock_request = MockRequest(method=method, url=api_base, headers=prepared_headers, body=body)

            # Sign the request using the provided OCI signer
            oci_signer.do_request_sign(mock_request, enforce_content_headers=True)

            # Update headers with signed headers
            headers.update(mock_request.headers)

            return headers, body

        # For standard auth, use original signing
        return original_sign_request(
            self, headers, optional_params, request_data, api_base, api_key, model, stream, fake_stream
        )

    # Mark it to avoid double patching
    custom_sign_request._is_custom_patch = True

    # Patch it
    OCIChatConfig.sign_request = custom_sign_request
