"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LiteLLM Patch Orchestrator
==========================
This module serves as the entry point for all litellm patches.
It imports and applies patches from specialized modules:

- litellm_patch_transform: Ollama transform_response patch for non-streaming responses
- litellm_patch_oci_auth: OCI authentication patches (instance principals, request signing)
- litellm_patch_oci_streaming: OCI streaming patches (tool call field fixes)

All patches use guard checks to prevent double-patching.
"""
# spell-checker:ignore litellm

from common import logging_config

logger = logging_config.logging.getLogger("patches.litellm_patch")

logger.info("Loading litellm patches...")

# Import patch modules - they apply patches on import
# pylint: disable=unused-import
try:
    from . import litellm_patch_transform

    logger.info("✓ Ollama transform_response patch loaded")
except Exception as e:
    logger.error("✗ Failed to load Ollama transform patch: %s", e)

try:
    from . import litellm_patch_oci_streaming

    logger.info("✓ OCI streaming patches loaded (handle_generic_stream_chunk)")
except Exception as e:
    logger.error("✗ Failed to load OCI streaming patches: %s", e)

logger.info("All litellm patches loaded successfully")
