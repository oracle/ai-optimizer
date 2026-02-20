"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

AI model registry and startup lifecycle.
"""

import logging

from .defaults import DEFAULT_MODELS
from .schemas import ModelConfig

LOGGER = logging.getLogger(__name__)


def _model_key(model_id: str, provider: str) -> tuple[str, str]:
    """Return the composite unique key for a model config."""
    return (model_id.casefold(), provider.casefold())


def register_model(model: ModelConfig) -> None:
    """Append *model* to settings.model_configs (deduplicate by (id, provider), last-write wins)."""
    from server.app.core.settings import settings  # pylint: disable=import-outside-toplevel

    key = _model_key(model.id, model.provider)
    settings.model_configs = [
        m for m in settings.model_configs if _model_key(m.id, m.provider) != key
    ] + [model]


async def load_default_models() -> None:
    """Startup entry point: populate model_configs with built-in defaults."""
    from server.app.core.settings import settings  # pylint: disable=import-outside-toplevel

    if settings.model_configs:
        LOGGER.info('Model configs already populated (%d), skipping defaults', len(settings.model_configs))
        return

    for entry in DEFAULT_MODELS:
        register_model(ModelConfig(**entry))

    LOGGER.info('Loaded %d default model config(s)', len(settings.model_configs))
