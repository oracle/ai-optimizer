"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.core.embed_status — the active-embed-jobs banner
helper shown on the embedding tab and the database configuration tab.
"""
# spell-checker: disable

from unittest.mock import patch

import httpx
import pytest

from client.tests.conftest import AttrDict, base_test_settings, make_http_error

MODULE = "client.app.core.embed_status"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_state(extra=None):
    """Minimal session state for embed_status tests."""
    data = AttrDict(
        {
            "settings": base_test_settings(),
            "optimizer_client": "test-client",
        }
    )
    if extra:
        data.update(extra)
    return data


def _job(job_id="abcd1234abcd1234abcd1234abcd1234", status="running",
         stage="embedding", message="3 of 12 chunks"):
    """Build a fake EmbedJobInfo dict."""
    return {
        "job_id": job_id,
        "status": status,
        "created_at": "2026-05-06T00:00:00Z",
        "updated_at": "2026-05-06T00:00:01Z",
        "progress": {"stage": stage, "message": message},
    }


# ---------------------------------------------------------------------------
# _fetch_active_jobs
# ---------------------------------------------------------------------------
class TestFetchActiveJobs:
    """Tests for the API-call wrapper that returns only non-terminal jobs."""

    def test_returns_only_active_statuses(self):
        """Verify the request opts into the server-side active_only filter
        so terminal rows + their result blobs never leave the server.

        Client-side filtering of any 'leaked' terminal rows still
        runs as a defence-in-depth backstop in case an older server
        ignores the query string.
        """
        state = _make_state()
        # Server with the filter would only ever return queued/running.
        jobs = [
            _job(job_id="aaaa", status="queued"),
            _job(job_id="bbbb", status="running"),
        ]
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", return_value=jobs) as mock_get,
        ):
            from client.app.core.embed_status import _fetch_active_jobs

            active = _fetch_active_jobs()
        assert active is not None
        assert [j["job_id"] for j in active] == ["aaaa", "bbbb"]
        mock_get.assert_called_once_with(
            "embed/jobs",
            params={"active_only": "true"},
            extra_headers={"client": "test-client"},
            timeout=5,
        )

    def test_client_filter_is_defence_in_depth(self):
        """If an older server ignores ``active_only`` and returns terminal
        rows, the client still drops them so the active->idle hook is
        not corrupted by stale terminal data.
        """
        state = _make_state()
        jobs = [
            _job(job_id="aaaa", status="queued"),
            _job(job_id="bbbb", status="running"),
            _job(job_id="cccc", status="succeeded"),
            _job(job_id="dddd", status="failed"),
        ]
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", return_value=jobs),
        ):
            from client.app.core.embed_status import _fetch_active_jobs

            active = _fetch_active_jobs()
        assert active is not None
        assert [j["job_id"] for j in active] == ["aaaa", "bbbb"]

    def test_http_503_returns_none(self):
        """Verify a 503 (CORE temporarily unavailable) yields ``None``,
        signalling 'unknown' rather than 'no active jobs'.

        Returning [] would cause the active->idle refresh hook on the
        database tab to fire prematurely and clear the seen-active
        flag, so a job that actually completes during the outage
        would never trigger a refresh.
        """
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", side_effect=make_http_error(503, "CORE unavailable")),
        ):
            from client.app.core.embed_status import _fetch_active_jobs

            assert _fetch_active_jobs() is None

    def test_transport_error_returns_none(self):
        """Verify a transport error (server down, network) yields ``None``.

        Same reasoning as the 503 case: a no-response failure must not
        be confused with a successful 'no jobs running' response, or
        we'd lose the eventual active->idle transition.
        """
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", side_effect=httpx.ConnectError("down")),
        ):
            from client.app.core.embed_status import _fetch_active_jobs

            assert _fetch_active_jobs() is None

    def test_unknown_status_filtered_out(self):
        """Verify an unrecognised status (e.g. forward-compat 'paused') is treated as inactive."""
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", return_value=[_job(status="paused")]),
        ):
            from client.app.core.embed_status import _fetch_active_jobs

            assert _fetch_active_jobs() == []


# ---------------------------------------------------------------------------
# _render_jobs_panel
# ---------------------------------------------------------------------------
class TestRenderJobsPanel:
    """Tests for the inline status panel render."""

    def test_renders_one_line_per_active_job(self, mock_st):
        """Verify each active job produces a markdown line containing its short id and stage."""
        active = [
            _job(job_id="aaaa1111aaaa1111aaaa1111aaaa1111", stage="splitting", message=""),
            _job(job_id="bbbb2222bbbb2222bbbb2222bbbb2222", stage="embedding",
                 message="5 of 10"),
        ]
        with patch(f"{MODULE}.st", mock_st):
            from client.app.core.embed_status import _render_jobs_panel

            _render_jobs_panel(active)
        markdown_calls = [c.args[0] for c in mock_st.markdown.call_args_list]
        joined = "\n".join(markdown_calls)
        assert "aaaa1111" in joined  # short job id
        assert "bbbb2222" in joined
        # Stage labels are humanised — splitting becomes "Parsing & chunking".
        assert "Parsing" in joined or "splitting" in joined.lower()
        assert "5 of 10" in joined  # the user-visible message must show

    def test_renders_idle_message_when_no_active_jobs(self, mock_st):
        """Verify the panel emits an idle message rather than nothing.

        Showing the panel with an explicit "no jobs running" message
        prevents users from wondering whether the panel is broken or
        whether their job is actually running.
        """
        with patch(f"{MODULE}.st", mock_st):
            from client.app.core.embed_status import _render_jobs_panel

            _render_jobs_panel([])
        markdown_calls = [c.args[0] for c in mock_st.markdown.call_args_list]
        joined = " ".join(markdown_calls).lower()
        assert "no" in joined and "running" in joined

    def test_hide_when_idle_renders_nothing_on_no_jobs(self, mock_st):
        """Verify hide_when_idle suppresses both the container and the
        idle text when there are no active jobs.

        On the embedding tab the user is already in a workflow about to
        start a job; an empty banner is just visual noise. Callers opt
        in to suppression so the database tab can keep showing the
        reassurance line.
        """
        with patch(f"{MODULE}.st", mock_st):
            from client.app.core.embed_status import _render_jobs_panel

            _render_jobs_panel([], hide_when_idle=True)
        # No container is opened and no markdown line is emitted.
        mock_st.container.assert_not_called()
        mock_st.markdown.assert_not_called()

    def test_hide_when_idle_still_renders_when_jobs_active(self, mock_st):
        """Verify hide_when_idle does NOT suppress the panel when jobs are active."""
        active = [_job(job_id="aaaa1111aaaa1111aaaa1111aaaa1111", stage="embedding")]
        with patch(f"{MODULE}.st", mock_st):
            from client.app.core.embed_status import _render_jobs_panel

            _render_jobs_panel(active, hide_when_idle=True)
        mock_st.container.assert_called_once()
        # At least one markdown line per active job should be emitted.
        assert mock_st.markdown.call_count >= 1


# ---------------------------------------------------------------------------
# _maybe_refresh_on_idle
# ---------------------------------------------------------------------------
class TestMaybeRefreshOnIdle:
    """Tests for the disappearance-driven refresh hook.

    The seen set tracks every job_id the panel has observed; the
    refresh fires when any seen id is no longer present in the
    current active list. This is what lets concurrent jobs trigger
    independent refreshes — a single boolean would force the second
    completion to wait until the first finished too.
    """

    def test_active_jobs_added_to_seen_set(self):
        """Verify every active job_id ends up in the seen set so
        we can detect its eventual disappearance."""
        state = _make_state()
        active = [_job(job_id="aaaa"), _job(job_id="bbbb")]
        with patch(f"{MODULE}.state", state):
            from client.app.core.embed_status import (
                _SEEN_JOBS_KEY,
                _maybe_refresh_on_idle,
            )

            _maybe_refresh_on_idle(active, refresh_on_idle=True)
        assert state.get(_SEEN_JOBS_KEY) == {"aaaa", "bbbb"}

    def test_idle_with_refresh_off_does_nothing(self, mock_st):
        """Verify caller without refresh_on_idle never invokes refresh_settings."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            from client.app.core.embed_status import _maybe_refresh_on_idle

            _maybe_refresh_on_idle([], refresh_on_idle=False)
        mock_helpers.refresh_settings.assert_not_called()
        mock_st.rerun.assert_not_called()

    def test_idle_with_refresh_on_no_prior_seen_does_nothing(self, mock_st):
        """Verify a database-page render with refresh_on_idle but no prior
        observed jobs does NOT trigger a refresh — only an actual
        observed-then-vanished job should refresh.
        """
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            from client.app.core.embed_status import _maybe_refresh_on_idle

            _maybe_refresh_on_idle([], refresh_on_idle=True)
        mock_helpers.refresh_settings.assert_not_called()
        mock_st.rerun.assert_not_called()

    def test_seen_then_vanished_triggers_refresh_and_rerun(self, mock_st):
        """Verify a previously-seen job that's no longer active triggers
        exactly one refresh+rerun and the completed id is dropped from seen."""
        state = _make_state({"_embed_jobs_seen_ids": {"aaaa"}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.refresh_settings.return_value = True
            from client.app.core.embed_status import _maybe_refresh_on_idle

            _maybe_refresh_on_idle([], refresh_on_idle=True)
        mock_helpers.refresh_settings.assert_called_once_with(clear_runtime=False)
        mock_st.rerun.assert_called_once()
        assert "_embed_jobs_seen_ids" not in state

    def test_failed_refresh_preserves_seen_set_and_skips_rerun(self, mock_st):
        """When refresh_settings returns False (server briefly down), the
        seen set must be retained so a later tick can retry.

        Skipping ``st.rerun`` on failure also matters: rerunning to show
        the same stale state is a wasted render and (on the embedding
        tab) erases any error message the user is mid-reading.
        """
        state = _make_state({"_embed_jobs_seen_ids": {"aaaa"}})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.refresh_settings.return_value = False
            from client.app.core.embed_status import _maybe_refresh_on_idle

            _maybe_refresh_on_idle([], refresh_on_idle=True)
        mock_helpers.refresh_settings.assert_called_once_with(clear_runtime=False)
        mock_st.rerun.assert_not_called()
        assert state.get("_embed_jobs_seen_ids") == {"aaaa"}, (
            "seen set must persist when refresh_settings returns False so a "
            "later tick can retry"
        )

    def test_concurrent_jobs_one_completes_triggers_refresh(self, mock_st):
        """[P2] Two jobs in flight; one completes while the other still
        runs. The fragment must refresh on that completion, not wait
        for both to finish.

        With a boolean flag this scenario silently failed: A's
        completion left ``active_count = 1`` so ``refresh_on_idle``
        re-set the flag and skipped the refresh, hiding A's new
        vector store for the entire remaining duration of B.
        """
        from client.app.core.embed_status import (
            _SEEN_JOBS_KEY,
            _maybe_refresh_on_idle,
        )

        state = _make_state()

        # Tick 1: both jobs observed.
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.refresh_settings.return_value = True
            _maybe_refresh_on_idle(
                [_job(job_id="job-a"), _job(job_id="job-b")],
                refresh_on_idle=True,
            )
        assert state.get(_SEEN_JOBS_KEY) == {"job-a", "job-b"}
        mock_helpers.refresh_settings.assert_not_called()
        mock_st.rerun.assert_not_called()

        # Tick 2: A completes, B still running. A is in seen but not
        # in current — that's the disappearance signal.
        # Reset rerun's call history so we measure tick-2 refreshes
        # independently from any later tick.
        mock_st.rerun.reset_mock()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.refresh_settings.return_value = True
            _maybe_refresh_on_idle(
                [_job(job_id="job-b")],
                refresh_on_idle=True,
            )
        mock_helpers.refresh_settings.assert_called_once_with(clear_runtime=False)
        mock_st.rerun.assert_called_once()
        # Seen set now reflects only the still-active job — A was
        # dropped after the successful refresh, B remains so the
        # NEXT completion triggers its own refresh.
        assert state.get(_SEEN_JOBS_KEY) == {"job-b"}

        # Tick 3: B also completes. This should fire its own refresh
        # rather than being silently absorbed.
        mock_st.rerun.reset_mock()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.refresh_settings.return_value = True
            _maybe_refresh_on_idle([], refresh_on_idle=True)
        mock_helpers.refresh_settings.assert_called_once_with(clear_runtime=False)
        mock_st.rerun.assert_called_once()
        assert _SEEN_JOBS_KEY not in state

    def test_seen_baseline_maintained_even_when_refresh_off(self):
        """When ``refresh_on_idle`` is False, the seen set is still
        updated so a tab that later turns the flag on has the right
        starting baseline. Without this, a user who starts a job on
        the embedding tab (refresh_on_idle=False) and then visits the
        database tab (refresh_on_idle=True) would lose the seen-set
        signal at the tab boundary.
        """
        from client.app.core.embed_status import (
            _SEEN_JOBS_KEY,
            _maybe_refresh_on_idle,
        )

        state = _make_state()
        with patch(f"{MODULE}.state", state):
            _maybe_refresh_on_idle(
                [_job(job_id="job-a")],
                refresh_on_idle=False,
            )
        assert state.get(_SEEN_JOBS_KEY) == {"job-a"}


# ---------------------------------------------------------------------------
# mark_embed_job_started / clear_embed_job_flag — submit-time hooks
# ---------------------------------------------------------------------------
class TestSubmitTimeHooks:
    """Tests for the submit-time flag setter/clearer that lets the panel
    detect off-page completions even when the fragment never observes
    the running state.
    """

    def test_mark_embed_job_started_adds_to_seen_set(self):
        """mark_embed_job_started adds the job_id to the seen set.

        Without this, a job that finishes before the user navigates
        back to the panel page is never detected as a completion: the
        first fragment tick sees no active jobs and skips the refresh
        because the seen set was empty.
        """
        state = _make_state()
        with patch(f"{MODULE}.state", state):
            from client.app.core.embed_status import (
                _SEEN_JOBS_KEY,
                mark_embed_job_started,
            )

            mark_embed_job_started("job-aaaa")
        assert state.get(_SEEN_JOBS_KEY) == {"job-aaaa"}

    def test_mark_embed_job_started_accumulates_concurrent_submissions(self):
        """Multiple submissions in the same session each add their id."""
        state = _make_state()
        with patch(f"{MODULE}.state", state):
            from client.app.core.embed_status import (
                _SEEN_JOBS_KEY,
                mark_embed_job_started,
            )

            mark_embed_job_started("job-aaaa")
            mark_embed_job_started("job-bbbb")
        assert state.get(_SEEN_JOBS_KEY) == {"job-aaaa", "job-bbbb"}

    def test_clear_embed_job_flag_specific_id_removes_only_that(self):
        """clear_embed_job_flag(job_id) removes only the given id, leaving
        any other in-flight submissions intact.

        Without this granularity, the success handler clearing one
        completed job would also drop tracking for any concurrent
        sibling job, so the panel would miss the sibling's completion.
        """
        state = _make_state({"_embed_jobs_seen_ids": {"job-aaaa", "job-bbbb"}})
        with patch(f"{MODULE}.state", state):
            from client.app.core.embed_status import (
                _SEEN_JOBS_KEY,
                clear_embed_job_flag,
            )

            clear_embed_job_flag("job-aaaa")
        assert state.get(_SEEN_JOBS_KEY) == {"job-bbbb"}

    def test_clear_embed_job_flag_idempotent(self):
        """Clearing an unknown id (or with the set empty) is a no-op."""
        state = _make_state()
        with patch(f"{MODULE}.state", state):
            from client.app.core.embed_status import clear_embed_job_flag

            clear_embed_job_flag("job-not-tracked")  # empty set
            state["_embed_jobs_seen_ids"] = {"a"}
            clear_embed_job_flag("job-not-tracked")  # id not present
        assert state.get("_embed_jobs_seen_ids") == {"a"}


# ---------------------------------------------------------------------------
# render_active_embed_jobs (public entry point)
# ---------------------------------------------------------------------------
class TestRenderActiveEmbedJobs:
    """Tests for the public helper that pages call."""

    def test_invokes_fragment(self):
        """Verify the public helper delegates to the polling fragment."""
        with patch(f"{MODULE}._embed_jobs_fragment") as mock_fragment:
            from client.app.core.embed_status import render_active_embed_jobs

            render_active_embed_jobs()
        mock_fragment.assert_called_once_with(refresh_on_idle=False, hide_when_idle=False)

    def test_passes_refresh_on_idle(self):
        """Verify refresh_on_idle is forwarded so the database page can opt in."""
        with patch(f"{MODULE}._embed_jobs_fragment") as mock_fragment:
            from client.app.core.embed_status import render_active_embed_jobs

            render_active_embed_jobs(refresh_on_idle=True)
        mock_fragment.assert_called_once_with(refresh_on_idle=True, hide_when_idle=False)

    def test_passes_hide_when_idle(self):
        """Verify hide_when_idle is forwarded so the embedding tab can opt in."""
        with patch(f"{MODULE}._embed_jobs_fragment") as mock_fragment:
            from client.app.core.embed_status import render_active_embed_jobs

            render_active_embed_jobs(hide_when_idle=True)
        mock_fragment.assert_called_once_with(refresh_on_idle=False, hide_when_idle=True)


# ---------------------------------------------------------------------------
# _embed_jobs_fragment body (the function that st.fragment wraps)
# ---------------------------------------------------------------------------
class TestEmbedJobsFragmentBody:
    """Tests for the fragment body via its underlying ``__wrapped__`` view.

    ``st.fragment`` wraps the function but exposes the original via
    ``__wrapped__`` (functools convention). Calling the wrapped view
    bypasses Streamlit's per-tick orchestration so we can verify the
    fragment's behaviour without spinning up a Streamlit script run.
    """

    @staticmethod
    def _bare(fragment):
        """Return the underlying function under whatever attribute the
        decorator chose to stash it (``__wrapped__`` is the stable
        functools convention)."""
        return getattr(fragment, "__wrapped__", fragment)

    def test_renders_fetched_jobs_and_runs_idle_check(self, mock_st):
        """Verify the fragment fetches, renders, and forwards the idle hook
        with the full active-jobs list (not just a count).
        """
        state = _make_state()
        active = [_job()]
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_active_jobs", return_value=active) as mock_fetch,
            patch(f"{MODULE}._render_jobs_panel") as mock_render,
            patch(f"{MODULE}._maybe_refresh_on_idle") as mock_idle,
        ):
            from client.app.core import embed_status

            self._bare(embed_status._embed_jobs_fragment)(refresh_on_idle=True, hide_when_idle=False)
        mock_fetch.assert_called_once_with()
        mock_render.assert_called_once_with(active, hide_when_idle=False)
        # The idle hook must receive the full list so it can compute
        # set differences against the seen set; passing only ``len``
        # would lose the per-job_id signal needed for concurrent jobs.
        mock_idle.assert_called_once_with(active, refresh_on_idle=True)

    def test_passes_empty_list_to_idle_check_when_no_jobs(self, mock_st):
        """Verify the idle hook is called with [] when no jobs are active."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_active_jobs", return_value=[]),
            patch(f"{MODULE}._render_jobs_panel"),
            patch(f"{MODULE}._maybe_refresh_on_idle") as mock_idle,
        ):
            from client.app.core import embed_status

            self._bare(embed_status._embed_jobs_fragment)(refresh_on_idle=False, hide_when_idle=False)
        mock_idle.assert_called_once_with([], refresh_on_idle=False)

    def test_forwards_hide_when_idle_to_panel(self, mock_st):
        """Verify hide_when_idle propagates from fragment body to the panel renderer.

        The idle hook still runs even when the panel is suppressed, so
        the active->idle transition can refresh on the database tab
        even if the embedding tab opts to hide on idle.
        """
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_active_jobs", return_value=[]),
            patch(f"{MODULE}._render_jobs_panel") as mock_render,
            patch(f"{MODULE}._maybe_refresh_on_idle") as mock_idle,
        ):
            from client.app.core import embed_status

            self._bare(embed_status._embed_jobs_fragment)(refresh_on_idle=False, hide_when_idle=True)
        mock_render.assert_called_once_with([], hide_when_idle=True)
        mock_idle.assert_called_once_with([], refresh_on_idle=False)

    def test_fetch_failure_skips_render_and_idle_hook(self, mock_st):
        """Verify a None return from _fetch_active_jobs (fetch failed)
        skips rendering and the idle hook entirely.

        Calling the idle hook with 0 would clear the seen-active flag,
        defeating the eventual refresh-on-completion. Skipping both
        leaves the panel in its previous state and preserves the flag.
        """
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_active_jobs", return_value=None),
            patch(f"{MODULE}._render_jobs_panel") as mock_render,
            patch(f"{MODULE}._maybe_refresh_on_idle") as mock_idle,
        ):
            from client.app.core import embed_status

            self._bare(embed_status._embed_jobs_fragment)(refresh_on_idle=True, hide_when_idle=False)
        mock_render.assert_not_called()
        mock_idle.assert_not_called()

    def test_off_page_completion_still_refreshes(self, mock_st):
        """End-to-end: a job submitted just before navigating to a page
        without the panel must still refresh state on return.

        Sequence:
          1. POST /embed/ accepts the job — caller marks the seen set.
          2. User navigates to a panel-less page; no fragment tick
             ever observes the running state.
          3. Server completes the job off-page.
          4. User returns; the first fragment tick on the panel page
             sees no active jobs (``active_only=true`` returns []).

        Without the submit-time mark, step 4 has an empty seen set
        and skips the refresh. With the mark, the disappearance is
        detected and the refresh fires.
        """
        from client.app.core import embed_status

        state = _make_state()

        # Step 1: submission adds job_id to seen set — even though no
        # fragment tick ever ran.
        with patch(f"{MODULE}.state", state):
            embed_status.mark_embed_job_started("job-aaaa")
        assert state.get(embed_status._SEEN_JOBS_KEY) == {"job-aaaa"}

        # Steps 2-3 are off-page; no calls to the fragment.

        # Step 4: user returns to the panel page. First tick sees [].
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_active_jobs", return_value=[]),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            hlp.refresh_settings.return_value = True
            self._bare(embed_status._embed_jobs_fragment)(
                refresh_on_idle=True, hide_when_idle=False,
            )
        hlp.refresh_settings.assert_called_once_with(clear_runtime=False)
        mock_st.rerun.assert_called_once()
        assert embed_status._SEEN_JOBS_KEY not in state

    def test_fetch_failure_preserves_seen_set_end_to_end(self, mock_st):
        """End-to-end: an active job, then a transient 503, then a real
        completion must still trigger the refresh on the database tab.

        Without the fix, the transient failure round would clear the
        seen set and the eventual completion would silently skip the
        refresh. The test runs the real fragment body three times in
        sequence with the set living in real session state.
        """
        from client.app.core import embed_status

        state = _make_state()
        active_job = _job(job_id="job-aaaa", status="running")

        # Tick 1: job is running. Fragment adds it to the seen set.
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_active_jobs", return_value=[active_job]),
            patch(f"{MODULE}.helpers"),
        ):
            self._bare(embed_status._embed_jobs_fragment)(refresh_on_idle=True, hide_when_idle=False)
        assert state.get(embed_status._SEEN_JOBS_KEY) == {"job-aaaa"}

        # Tick 2: transient 503 — fetch returns None. Seen set must NOT be cleared.
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_active_jobs", return_value=None),
            patch(f"{MODULE}.helpers") as hlp_during_outage,
        ):
            self._bare(embed_status._embed_jobs_fragment)(refresh_on_idle=True, hide_when_idle=False)
        assert state.get(embed_status._SEEN_JOBS_KEY) == {"job-aaaa"}, (
            "transient fetch failure must not clear the seen set"
        )
        hlp_during_outage.refresh_settings.assert_not_called()

        # Tick 3: job actually completed — fetch returns []. NOW the
        # disappearance refresh must fire.
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_active_jobs", return_value=[]),
            patch(f"{MODULE}.helpers") as hlp_on_completion,
        ):
            hlp_on_completion.refresh_settings.return_value = True
            self._bare(embed_status._embed_jobs_fragment)(refresh_on_idle=True, hide_when_idle=False)
        hlp_on_completion.refresh_settings.assert_called_once_with(clear_runtime=False)
        mock_st.rerun.assert_called()
        assert embed_status._SEEN_JOBS_KEY not in state
