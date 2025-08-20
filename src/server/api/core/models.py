"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from typing import Optional, Union

from server.api.core import bootstrap

from common.schema import Model, ModelIdType, ModelTypeType
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

    if any(d.id == model.id for d in model_objects):
        raise ExistsModelError(f"Model: {model.id} already exists.")

    if not model.openai_compat:
        openai_compat = next(
            (model_config.openai_compat for model_config in model_objects if model_config.provider == model.provider),
            False,
        )
        model.openai_compat = openai_compat
    if check_url and model.url and not is_url_accessible(model.url)[0]:
        model.enabled = False

    model_objects.append(model)

    return get_model(model_id=model.id, model_type=model.type)


def delete_model(model_id: ModelIdType) -> None:
    """Remove model from model objects"""
    model_objects = bootstrap.MODEL_OBJECTS
    bootstrap.MODEL_OBJECTS = [model for model in model_objects if model.id != model_id]
