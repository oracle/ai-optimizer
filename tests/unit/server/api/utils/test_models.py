"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker: disable
import os
import pytest

import server.api.core.models as core_models
import server.api.utils.models as utils_models

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["LITELLM_DISABLE_SPEND_LOGS"] = "True"
os.environ["LITELLM_DISABLE_SPEND_UPDATES"] = "True"
os.environ["LITELLM_DISABLE_END_USER_COST_TRACKING"] = "True"
os.environ["LITELLM_DROP_PARAMS"] = "True"
os.environ["LITELLM_DROP_PARAMS"] = "True"

@pytest.fixture(name="models_list")
def _models_list():
    model_objects = core_models.get_model()
    for obj in model_objects:
        obj.enabled = True
    return model_objects


def test_get_litellm_client(models_list):
    """Testing LiteLLM Functionality"""
    assert isinstance(models_list, list)
    assert len(models_list) > 0

    for model in models_list:
        print(f"My Model: {model}")
        if model.id == "mxbai-embed-large":
            utils_models.get_litellm_client(model.dict())
