"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Active embedding jobs status panel — shared between the embedding tools
tab and the database configuration tab so users see job progress
regardless of where they navigated to mid-job.
"""

import logging

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import api_get

LOGGER = logging.getLogger("client.core.embed_status")

_ACTIVE_STATUSES = frozenset({"queued", "running"})
# Set of job_ids the panel has observed in this session. Tracked as a
# set rather than a boolean so the refresh hook fires on ANY observed-
# then-vanished job; with a boolean, two concurrent jobs would force
# the first completion to wait until the second also finished.
_SEEN_JOBS_KEY = "_embed_jobs_seen_ids"
_POLL_INTERVAL = 2.0
_LIST_TIMEOUT = 5

# Stage labels for the populate poller's progress toast and the
# panel's per-job line. Unknown stages fall through to the raw value
# so adding a stage server-side does not break the UI.
_STAGE_LABELS: dict[str, str] = {
    "queued": "Queued",
    "preparing": "Preparing files",
    "splitting": "Parsing & chunking",
    "embedding": "Embedding chunks",
    "indexing": "Building vector index",
    "finalizing": "Updating metadata",
}


def _fetch_active_jobs() -> list[dict] | None:
    """Return active jobs, or ``None`` on a fetch failure.

    The tri-state contract is load-bearing: returning ``[]`` on a
    transient 503 / transport error would clear the seen set and
    fire the refresh prematurely, losing the eventual real
    active->idle transition if the outage outlives the job.
    """
    try:
        jobs = api_get(
            "embed/jobs",
            params={"active_only": "true"},
            extra_headers={"client": state.optimizer_client},
            timeout=_LIST_TIMEOUT,
        )
    except httpx.HTTPError as ex:
        LOGGER.debug("embed/jobs poll failed (%s); fetch state unknown", ex)
        return None
    # Extra compatibility check: a stale server (rolling deploy) might
    # ignore the active_only filter; drop terminal rows locally.
    return [j for j in jobs if j.get("status") in _ACTIVE_STATUSES]


def _render_jobs_panel(active: list[dict], *, hide_when_idle: bool = False) -> None:
    """Render the active-jobs panel inline on the calling page.

    With ``hide_when_idle``, the panel emits nothing on the no-jobs
    branch — used in workflow contexts like the embedding tab where
    an empty banner is just visual noise.
    """
    if not active:
        if hide_when_idle:
            return
        with st.container(border=True):
            st.markdown("**No embedding jobs running.**")
        return
    with st.container(border=True):
        plural = "s" if len(active) > 1 else ""
        st.markdown(f"**🛠️ Active embedding job{plural} ({len(active)})**")
        for job in active:
            progress = job.get("progress") or {}
            stage = progress.get("stage") or job.get("status", "")
            label = _STAGE_LABELS.get(stage, stage or "Working")
            message = progress.get("message") or ""
            short_id = (job.get("job_id") or "")[:8]
            line = f"- `{short_id}` — **{label}**"
            if message:
                line += f" — {message}"
            st.markdown(line)


def _maybe_refresh_on_idle(active_jobs: list[dict], *, refresh_on_idle: bool) -> None:
    """Refresh settings when any previously-observed job disappears.

    The seen set is updated on every tick regardless of
    ``refresh_on_idle`` so a tab without the auto-refresh hook still
    maintains the right baseline if the user later navigates to a
    tab that does. On refresh failure the seen set is preserved so
    the next tick can retry.
    """
    current_ids = {j["job_id"] for j in active_jobs if j.get("job_id")}
    seen_ids: set[str] = set(state.get(_SEEN_JOBS_KEY, set()))
    seen_ids |= current_ids
    completed_ids = seen_ids - current_ids

    if not refresh_on_idle or not completed_ids:
        if seen_ids:
            state[_SEEN_JOBS_KEY] = seen_ids
        else:
            state.pop(_SEEN_JOBS_KEY, None)
        return

    if not helpers.refresh_settings(clear_runtime=False):
        state[_SEEN_JOBS_KEY] = seen_ids
        return

    if current_ids:
        state[_SEEN_JOBS_KEY] = current_ids
    else:
        state.pop(_SEEN_JOBS_KEY, None)
    st.rerun()


@st.fragment(run_every=_POLL_INTERVAL)
def _embed_jobs_fragment(refresh_on_idle: bool = False, hide_when_idle: bool = False) -> None:
    """Polling fragment body. A fetch failure (``None``) skips both
    render and the idle hook so the seen set survives transient
    CORE outages.
    """
    active = _fetch_active_jobs()
    if active is None:
        return
    _render_jobs_panel(active, hide_when_idle=hide_when_idle)
    _maybe_refresh_on_idle(active, refresh_on_idle=refresh_on_idle)


def mark_embed_job_started(job_id: str) -> None:
    """Add ``job_id`` to the per-session seen set on a successful POST 202,
    so an off-page completion (user navigated before any fragment tick
    observed the running state) still triggers the refresh on return.
    """
    seen: set[str] = set(state.get(_SEEN_JOBS_KEY, set()))
    seen.add(job_id)
    state[_SEEN_JOBS_KEY] = seen


def clear_embed_job_flag(job_id: str) -> None:
    """Remove a specific id from the seen set. Idempotent on unknown ids.

    Specific-id only: a whole-set clear would drop tracking for any
    concurrent sibling job in flight.
    """
    seen: set[str] = set(state.get(_SEEN_JOBS_KEY, set()))
    seen.discard(job_id)
    if seen:
        state[_SEEN_JOBS_KEY] = seen
    else:
        state.pop(_SEEN_JOBS_KEY, None)


def render_active_embed_jobs(*, refresh_on_idle: bool = False, hide_when_idle: bool = False) -> None:
    """Display the active embedding jobs panel on the calling page.

    ``refresh_on_idle``: fire ``helpers.refresh_settings`` when an
    observed job disappears — for pages that read
    ``state.settings.database_configs``.
    ``hide_when_idle``: render nothing when no jobs are active —
    for in-workflow placements like the embedding tab.
    """
    _embed_jobs_fragment(refresh_on_idle=refresh_on_idle, hide_when_idle=hide_when_idle)
