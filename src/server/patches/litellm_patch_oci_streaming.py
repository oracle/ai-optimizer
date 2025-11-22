"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI Streaming Patches
=====================
Patches for OCI GenAI service streaming responses with tool calls.

Issue: OCI API returns tool calls without 'arguments' field, causing Pydantic validation error
Error: ValidationError: 1 validation error for OCIStreamChunk message.toolCalls.0.arguments Field required

This happens when OCI models (e.g., meta.llama-3.1-405b-instruct) attempt tool calling but return
incomplete tool call structures missing the required 'arguments' field during streaming.

This module patches OCIStreamWrapper._handle_generic_stream_chunk to add missing required fields
with empty defaults before Pydantic validation.
"""
# spell-checker:ignore litellm giskard ollama llms
# pylint: disable=unused-argument,protected-access

from common import logging_config

logger = logging_config.logging.getLogger("patches.litellm_patch_oci_streaming")

# Patch OCI _handle_generic_stream_chunk to add missing 'arguments' field in tool calls
try:
    from litellm.llms.oci.chat.transformation import OCIStreamWrapper

    original_handle_generic_stream_chunk = getattr(OCIStreamWrapper, "_handle_generic_stream_chunk", None)
except ImportError:
    original_handle_generic_stream_chunk = None

if original_handle_generic_stream_chunk and not getattr(
    original_handle_generic_stream_chunk, "_is_custom_patch", False
):
    from litellm.llms.oci.chat.transformation import (
        OCIStreamChunk,
        OCITextContentPart,
        OCIImageContentPart,
        adapt_tools_to_openai_standard,
    )
    from litellm.types.utils import ModelResponseStream, StreamingChoices, Delta

    def custom_handle_generic_stream_chunk(self, dict_chunk: dict):
        """
        Custom handler to fix missing 'arguments' field in OCI tool calls.

        OCI API sometimes returns tool calls with structure:
        {'type': 'FUNCTION', 'id': '...', 'name': 'tool_name'}

        But OCIStreamChunk Pydantic model requires 'arguments' field in tool calls.
        This patch adds an empty arguments dict if missing.
        """
        # Fix missing required fields in tool calls before Pydantic validation
        # OCI streams tool calls progressively, so early chunks may be missing required fields
        if dict_chunk.get("message") and dict_chunk["message"].get("toolCalls"):
            for tool_call in dict_chunk["message"]["toolCalls"]:
                missing_fields = []
                if "arguments" not in tool_call:
                    tool_call["arguments"] = ""
                    missing_fields.append("arguments")
                if "id" not in tool_call:
                    tool_call["id"] = ""
                    missing_fields.append("id")
                if "name" not in tool_call:
                    tool_call["name"] = ""
                    missing_fields.append("name")

                if missing_fields:
                    logger.debug(
                        "OCI tool call streaming chunk missing fields: %s (Type: %s) - adding empty defaults",
                        missing_fields,
                        tool_call.get("type", "unknown"),
                    )

        # Now proceed with original validation and processing
        try:
            typed_chunk = OCIStreamChunk(**dict_chunk)
        except TypeError as e:
            raise ValueError(f"Chunk cannot be casted to OCIStreamChunk: {str(e)}") from e

        if typed_chunk.index is None:
            typed_chunk.index = 0

        text = ""
        if typed_chunk.message and typed_chunk.message.content:
            for item in typed_chunk.message.content:
                if isinstance(item, OCITextContentPart):
                    text += item.text
                elif isinstance(item, OCIImageContentPart):
                    raise ValueError("OCI does not support image content in streaming responses")
                else:
                    raise ValueError(f"Unsupported content type in OCI response: {item.type}")

        tool_calls = None
        if typed_chunk.message and typed_chunk.message.toolCalls:
            tool_calls = adapt_tools_to_openai_standard(typed_chunk.message.toolCalls)

        return ModelResponseStream(
            choices=[
                StreamingChoices(
                    index=typed_chunk.index if typed_chunk.index else 0,
                    delta=Delta(
                        content=text,
                        tool_calls=[tool.model_dump() for tool in tool_calls] if tool_calls else None,
                        provider_specific_fields=None,
                        thinking_blocks=None,
                        reasoning_content=None,
                    ),
                    finish_reason=typed_chunk.finishReason,
                )
            ]
        )

    # Mark it to avoid double patching
    custom_handle_generic_stream_chunk._is_custom_patch = True

    # Patch it
    OCIStreamWrapper._handle_generic_stream_chunk = custom_handle_generic_stream_chunk
