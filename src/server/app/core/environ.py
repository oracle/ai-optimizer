"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Side-effect module: sets dependency environment variables via os.environ.setdefault().

Import this module before any third-party library that reads these variables.
In Docker containers the Dockerfile ENV directives supply container-specific paths
(e.g. /app/tmp) and take precedence because setdefault never overwrites.
"""
# spell-checker: ignore giskard litellm mplconfigdir

import os
import tempfile

_cache_dir = os.path.join(tempfile.gettempdir(), "ai-optimizer")

# LiteLLM - use bundled cost map instead of fetching from GitHub
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# Giskard - disable error reporting and telemetry
os.environ.setdefault("GSK_DISABLE_SENTRY", "True")
os.environ.setdefault("GSK_DISABLE_ANALYTICS", "True")

# HuggingFace tokenizers - suppress fork-safety warnings
os.environ.setdefault("TOKENIZERS_PARALLELISM", "true")

# Cache / data directories (Docker overrides these to /app/tmp)
os.environ.setdefault("NUMBA_CACHE_DIR", _cache_dir)
os.environ.setdefault("MPLCONFIGDIR", _cache_dir)
os.environ.setdefault("TIKTOKEN_CACHE_DIR", _cache_dir)
os.environ.setdefault("NLTK_DATA", _cache_dir)
