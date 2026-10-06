"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for Testbed Giskard model adapters.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from giskard.agents.generators import GenerationParams
from giskard.llm.types import UserMessage

from server.app.testbed.giskard_models import giskard_generator


@pytest.mark.unit
@pytest.mark.anyio
async def test_generator_forwards_connection_config_and_check_parameters():
    generator = giskard_generator(
        {
            "model": "oci/test-model",
            "api_key": "secret",
            "top_p": 0.8,
            "temperature": 0.2,
        }
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message={"role": "assistant", "content": "Answer"}, finish_reason="stop")]
    )
    with patch("server.app.testbed.giskard_models.litellm.acompletion", new_callable=AsyncMock) as completion:
        completion.return_value = response
        result = await generator._call_model(
            [UserMessage(content="Question")],
            GenerationParams(temperature=0.1),
        )

    assert completion.await_args is not None
    assert completion.await_args.kwargs["api_key"] == "secret"
    assert completion.await_args.kwargs["top_p"] == 0.8
    assert completion.await_args.kwargs["temperature"] == 0.1
    assert completion.await_args.kwargs["model"] == "oci/test-model"
    assert result.choices[0].message.content == "Answer"
    assert "secret" not in str(generator.model_dump())
