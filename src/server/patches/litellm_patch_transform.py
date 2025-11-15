"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore litellm giskard ollama llms
# pylint: disable=unused-argument,protected-access

from typing import TYPE_CHECKING, List, Optional, Any
import time
import litellm
from litellm.llms.ollama.completion.transformation import OllamaConfig
from litellm.types.llms.openai import AllMessageValues
from litellm.types.utils import ModelResponse
from httpx._models import Response

from common import logging_config

logger = logging_config.logging.getLogger("patches.litellm_patch_transform")

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
