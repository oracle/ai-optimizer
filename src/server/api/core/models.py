"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from typing import Optional, Union

from server.api.core import bootstrap

from common.schema import Model, ModelIdType, ModelProviderType, ModelTypeType
from common.functions import is_url_accessible
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.models")


#####################################################
# Exceptions
#####################################################
class URLUnreachableError(ValueError):
    """Raised when the submitted URL is unreachable."""


class InvalidModelError(ValueError):
    """Raised when the model data is invalid in some other way."""


class ExistsModelError(ValueError):
    """Raised when the model data already exist."""


class UnknownModelError(ValueError):
    """Raised when the model data doesn't exist."""


#####################################################
# Functions
#####################################################
def get_model(
    model_provider: Optional[ModelProviderType] = None,
    model_id: Optional[ModelIdType] = None,
    model_type: Optional[ModelTypeType] = None,
    include_disabled: bool = True,
) -> Union[list[Model], Model, None]:
    """Used in direct call from list_models and agents.models"""
    model_objects = bootstrap.MODEL_OBJECTS

    logger.debug("%i models are defined", len(model_objects))

    model_filtered = [
        model
        for model in model_objects
        if (model_id is None or model.id == model_id)
        and (model_type is None or model.type == model_type)
        and (model_provider is None or model.provider == model_provider)
        and (include_disabled or model.enabled)
    ]
    logger.debug("%i models after filtering", len(model_filtered))

    if model_id and not model_filtered:
        raise UnknownModelError(f"{model_id} not found")
    if model_type and not model_filtered:
        raise UnknownModelError(f"{model_type} not found")

    if len(model_filtered) == 1:
        return model_filtered[0]

    return model_filtered


def create_model(model: Model, check_url: bool = True) -> Model:
    """Create a new Model definition"""
    model_objects = bootstrap.MODEL_OBJECTS

    try:
        _ = get_model(model_id=model.id, model_provider=model.provider, model_type=model.type)
        raise ExistsModelError(f"Model: {model.id} already exists.")
    except UnknownModelError:
        pass

    if check_url and model.api_base and not is_url_accessible(model.api_base)[0]:
        model.enabled = False

    model_objects.append(model)
    return get_model(model_id=model.id, model_provider=model.provider, model_type=model.type)


def delete_model(model_provider: ModelProviderType, model_id: ModelIdType) -> None:
    """Remove model from model objects"""
    model_objects = bootstrap.MODEL_OBJECTS
    bootstrap.MODEL_OBJECTS = [m for m in model_objects if (m.id, m.provider) != (model_id, model_provider)]
