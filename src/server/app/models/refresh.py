"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Throttled, non-blocking re-probe of model endpoints so a provider that was down
at startup (e.g. Ollama) recovers without a server restart or manual refresh.

Re-probes existing configs only (via ``check_model_reachability``); it never runs
discovery, so a passive background refresh can't add or remove model configs.
"""

import asyncio
import logging
import time

from server.app.core.settings import _settings_lock
from server.app.models.connectivity import check_model_reachability

LOGGER = logging.getLogger(__name__)

# Minimum seconds between background re-probes triggered by settings fetches.
RECHECK_THROTTLE_SECONDS = 20.0
# Mutable container so the throttle state updates without a module-level ``global``.
# ``task`` holds a strong reference to the in-flight probe: the event loop only keeps
# a weak one, so without this the fire-and-forget task could be GC'd mid-run.
_recheck: dict = {"last_monotonic": 0.0, "task": None}


async def _run_recheck() -> None:
    """Re-probe every enabled endpoint and update its ``status``.

    Deliberately re-probes existing configs only — it does NOT run Ollama
    discovery. Discovery mutates the config set (adding pulled models, removing
    unpulled ones), which on a background timer would resurrect a model the user
    just deleted and delete a not-yet-pulled config. New models are picked up at
    startup or an explicit refresh, not by this passive recheck.

    Runs under ``_settings_lock`` so its status writes are serialized with the
    mutating endpoints (import/reset/update), which also probe under that lock —
    otherwise a stale background result could clobber a concurrent foreground change.
    """
    async with _settings_lock:
        await check_model_reachability()


def trigger_reachability_recheck(interval: float = RECHECK_THROTTLE_SECONDS) -> "asyncio.Task | None":
    """Start a background re-probe of model endpoints, at most once per *interval* seconds.

    Non-blocking: a model that was unreachable at startup recovers on a later
    settings fetch, without adding the blocking probes to the request path.
    Returns the scheduled task (for tests), or ``None`` when throttled.
    """
    now = time.monotonic()
    if now - _recheck["last_monotonic"] < interval:
        return None
    _recheck["last_monotonic"] = now
    _recheck["task"] = asyncio.create_task(_run_recheck())
    return _recheck["task"]
