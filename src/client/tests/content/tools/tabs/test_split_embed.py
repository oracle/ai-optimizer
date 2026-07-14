"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.tools.tabs.split_embed
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

pytestmark = pytest.mark.unit


class TestInlineUtilities:
    """Tests for private utility functions."""

    def test_is_url_accessible_empty(self):
        """Empty string returns False with an appropriate message."""
        from client.app.content.tools.tabs.split_embed import _is_url_accessible

        ok, msg = _is_url_accessible("")
        assert ok is False
        assert msg == "No URL Provided"

    def test_is_url_accessible_unrestricted_skips_validation(self):
        """Default (unrestricted) callers do not run the URL validator.

        Model api_base values such as ``http://127.0.0.1:11434`` are
        admin-controlled and must remain probable from the UI even
        though the same address class is rejected for user-typed Web
        URLs. The probe still happens; we just don't gate it through
        the user-URL validator.
        """
        from client.app.content.tools.tabs import split_embed

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_response)

        with (
            patch.object(split_embed, "validate_structural") as mock_validate,
            patch.object(split_embed.httpx, "Client", return_value=mock_client),
        ):
            split_embed._is_url_accessible.clear()
            ok, msg = split_embed._is_url_accessible("http://127.0.0.1:11434/api/tags")

        assert ok is True
        assert msg == ""
        mock_validate.assert_not_called()

    def test_is_url_accessible_restricted_blocks_denied(self):
        """Restricted mode rejects URLs that fail validate_safe_url."""
        from client.app.content.tools.tabs import split_embed

        with patch.object(
            split_embed,
            "validate_structural",
            side_effect=ValueError("URL cannot be used for this import."),
        ):
            split_embed._is_url_accessible.clear()
            ok, msg = split_embed._is_url_accessible("http://169.254.169.254/", restricted=True)

        assert ok is False
        assert msg == "URL cannot be used for this import."

    def test_is_url_accessible_restricted_follows_safe_redirect(self):
        """Restricted mode follows redirects after revalidating the target."""
        from client.app.content.tools.tabs import split_embed

        first = MagicMock()
        first.status_code = 302
        first.is_redirect = True
        first.headers = {"location": "https://final.example.com/"}

        final = MagicMock()
        final.status_code = 200
        final.is_redirect = False

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(side_effect=[first, final])

        with (
            patch.object(split_embed, "validate_structural", return_value=None),
            patch.object(split_embed.httpx, "Client", return_value=mock_client),
        ):
            split_embed._is_url_accessible.clear()
            ok, msg = split_embed._is_url_accessible("http://start.example.com/", restricted=True)

        assert ok is True
        assert msg == ""
        assert mock_client.get.call_count == 2

    def test_is_url_accessible_restricted_blocks_unsafe_redirect(self):
        """A redirect target that fails validation is rejected."""
        from client.app.content.tools.tabs import split_embed

        redirect = MagicMock()
        redirect.status_code = 302
        redirect.is_redirect = True
        redirect.headers = {"location": "http://10.0.0.1/"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=redirect)

        # First call (initial URL) succeeds; second call (redirect target)
        # raises through validate_safe_url.
        validate_results: list[Exception | None] = [None, ValueError("URL cannot be used for this import.")]

        def fake_validate(url: str) -> None:
            del url
            outcome = validate_results.pop(0)
            if isinstance(outcome, Exception):
                raise outcome

        with (
            patch.object(split_embed, "validate_structural", side_effect=fake_validate),
            patch.object(split_embed.httpx, "Client", return_value=mock_client),
        ):
            split_embed._is_url_accessible.clear()
            ok, msg = split_embed._is_url_accessible("http://start.example.com/", restricted=True)

        assert ok is False
        assert msg == "URL cannot be used for this import."

    def test_is_url_accessible_restricted_does_not_resolve_dns(self, monkeypatch):
        """In a proxy-only deployment, restricted mode must not call getaddrinfo.

        The previous full-DNS validation rejected legitimate public
        URLs whenever the application host could only resolve names
        through the proxy. Structural-only validation keeps the
        IP-literal deny-list active without needing local DNS.
        """
        import socket

        from client.app.content.tools.tabs import split_embed

        def explode(*_args, **_kwargs):
            raise AssertionError("getaddrinfo must not run for restricted probes")

        monkeypatch.setattr(socket, "getaddrinfo", explode)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=mock_response)

        with patch.object(split_embed.httpx, "Client", return_value=mock_client):
            split_embed._is_url_accessible.clear()
            ok, msg = split_embed._is_url_accessible("https://public.example.com/", restricted=True)

        assert ok is True
        assert msg == ""

    def test_is_url_accessible_restricted_handles_malformed_redirect(self):
        """A malformed Location header must surface as inaccessible, not a crash.

        ``httpx.URL.join`` raises ``httpx.InvalidURL`` for inputs like
        ``http://[::1`` (truncated bracket). That exception is *not* a
        subclass of ``httpx.HTTPError`` or ``ValueError``, so prior
        manual-redirect code let it escape to the Streamlit render.
        """
        from client.app.content.tools.tabs import split_embed

        redirect = MagicMock()
        redirect.status_code = 302
        redirect.is_redirect = True
        redirect.headers = {"location": "http://[::1"}  # malformed

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(return_value=redirect)

        with (
            patch.object(split_embed, "validate_structural", return_value=None),
            patch.object(split_embed.httpx, "Client", return_value=mock_client),
        ):
            split_embed._is_url_accessible.clear()
            ok, msg = split_embed._is_url_accessible("http://start.example.com/", restricted=True)

        assert ok is False
        assert "not accessible" in msg.lower() or msg == "URL cannot be used for this import."

    def test_is_url_accessible_unrestricted_treats_http_error_as_inaccessible(self):
        """Unrestricted callers still surface httpx errors with the URL."""
        from client.app.content.tools.tabs import split_embed

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get = MagicMock(side_effect=httpx.ConnectError("refused"))

        with patch.object(split_embed.httpx, "Client", return_value=mock_client):
            split_embed._is_url_accessible.clear()
            ok, msg = split_embed._is_url_accessible("http://127.0.0.1:11434/api/tags")

        assert ok is False
        assert "ConnectError" in msg

    def test_local_file_payload_deduplicates(self):
        """Duplicate filenames are collapsed to a single entry."""
        from client.app.core.helpers import unique_file_payload as _local_file_payload

        class FakeFile:
            """Minimal stand-in for a Streamlit UploadedFile."""

            def __init__(self, name, content=b"data", ftype="text/plain"):
                self.name = name
                self._content = content
                self.type = ftype

            def getvalue(self):
                """Return raw file bytes."""
                return self._content

        files = [FakeFile("a.txt"), FakeFile("a.txt"), FakeFile("b.txt")]
        result = _local_file_payload(files)
        assert len(result) == 2
        assert result[0][1][0] == "a.txt"
        assert result[1][1][0] == "b.txt"

    def test_generate_vs_table_name(self):
        """Alias and parameters are uppercased and joined into a deterministic name."""
        from client.app.content.tools.tabs.split_embed import _generate_vs_table_name

        name = _generate_vs_table_name(
            alias="test",
            model_key="oci/embed-v1",
            chunk_size=512,
            chunk_overlap=50,
            distance_strategy="COSINE",
            index_type="HNSW",
        )
        assert name is not None
        assert name == "TEST_OCI_EMBED_V1_512_50_COSINE_HNSW"

    def test_generate_vs_table_name_no_alias(self):
        """Empty alias still produces a valid name derived from the model key."""
        from client.app.content.tools.tabs.split_embed import _generate_vs_table_name

        name = _generate_vs_table_name(
            alias="",
            model_key="openai/text-embed-3",
            chunk_size=1024,
            chunk_overlap=100,
            distance_strategy="DOT",
        )
        assert name is not None
        assert "OPENAI_TEXT_EMBED_3" in name

    def test_validate_new_alias_valid(self):
        """Empty alias is treated as invalid (returns True for has-errors)."""
        from client.app.content.tools.tabs.split_embed import _validate_new_alias

        assert _validate_new_alias("") is True

    def test_build_embed_payload(self):
        """Config dict is transformed into the API payload format."""
        from client.app.content.tools.tabs.split_embed import _build_embed_payload

        config = {
            "model_key": "oci/embed-v1",
            "alias": "test",
            "description": "A test store",
            "chunk_size": 512,
            "chunk_overlap": 50,
            "distance_strategy": "COSINE",
            "index_type": "HNSW",
        }
        payload = _build_embed_payload(config)
        assert payload["embedding_model"] == {"provider": "oci", "id": "embed-v1"}
        assert payload["alias"] == "test"
        assert payload["distance_strategy"] == "COSINE"
        assert "model_key" not in payload

    def test_build_embed_payload_includes_filename_grouping(self):
        """Filename-grouped mode is sent to the embed API."""
        from client.app.content.tools.tabs.split_embed import _build_embed_payload

        payload = _build_embed_payload(
            {
                "model_key": "oci/embed-v1",
                "split_by_filename": True,
            }
        )

        assert payload["split_by_filename"] is True


class TestFileSourceData:
    """Tests for the FileSourceData dataclass."""

    def test_get_button_help(self):
        """Local source returns help text containing 'disabled'."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="Local")
        assert "disabled" in data.get_button_help().lower()

    def test_get_button_help_unknown(self):
        """Unknown source returns empty help text."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="Unknown")
        assert data.get_button_help() == ""

    def test_is_valid_oci_no_files_selected(self):
        """OCI source with no files checked is invalid."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        df = pd.DataFrame({"File": ["a.txt", "b.txt"], "Process": [False, False]})
        data = FileSourceData(file_source="OCI", oci_bucket="my-bucket", oci_files_selected=df)
        assert data.is_valid() is False

    def test_is_valid_oci_with_files_selected(self):
        """OCI source with at least one file checked is valid."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        df = pd.DataFrame({"File": ["a.txt", "b.txt"], "Process": [True, False]})
        data = FileSourceData(file_source="OCI", oci_bucket="my-bucket", oci_files_selected=df)
        assert data.is_valid() is True

    def test_is_valid_oci_none_dataframe(self):
        """OCI source with None dataframe is invalid."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="OCI", oci_bucket="my-bucket", oci_files_selected=None)
        assert data.is_valid() is False

    def test_is_valid_sql_with_query(self):
        """SQL source with a non-empty query and database alias is valid."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="SQL", sql_query="SELECT * FROM docs", sql_db_alias="CORE")
        assert data.is_valid() is True

    def test_is_valid_sql_empty_query(self):
        """SQL source with a whitespace-only query is invalid."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="SQL", sql_query="   ", sql_db_alias="CORE")
        assert data.is_valid() is False

    def test_is_valid_sql_no_db_alias(self):
        """SQL source with a valid query but no database alias is invalid."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="SQL", sql_query="SELECT * FROM docs")
        assert data.is_valid() is False

    def test_is_valid_unknown_source(self):
        """Unrecognised file source is always invalid."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="Unknown")
        assert data.is_valid() is False

    def test_oci_refresh_only_needs_bucket(self):
        """Refresh path should be ready with just a bucket and vector store, no file selection needed."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        df = pd.DataFrame({"File": ["a.txt"], "Process": [False]})
        data = FileSourceData(file_source="OCI", oci_bucket="my-bucket", oci_files_selected=df)
        # is_valid() is False (no files checked) but refresh only needs the bucket
        assert data.is_valid() is False
        is_refresh_ready = bool(data.oci_bucket) and bool("some_vector_store")
        assert is_refresh_ready is True

    def test_is_valid_oci_all_files_with_bucket(self):
        """Bucket-wide mode: a selected bucket is sufficient — no per-file selection needed."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="OCI", oci_bucket="my-bucket", oci_all_files=True)
        assert data.is_valid() is True

    def test_is_valid_oci_all_files_without_bucket(self):
        """Bucket-wide mode is invalid when no bucket is selected."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="OCI", oci_bucket=None, oci_all_files=True)
        assert data.is_valid() is False

    def test_get_button_help_oci_all_files(self):
        """Bucket-wide help text mentions the bucket requirement, not file selection."""
        from client.app.content.tools.tabs.split_embed import FileSourceData

        data = FileSourceData(file_source="OCI", oci_all_files=True)
        help_text = data.get_button_help().lower()
        assert "bucket" in help_text
        assert "documents" not in help_text


class TestPollEmbedJob:
    """Tests for ``_poll_embed_job`` — the Streamlit polling loop."""

    @staticmethod
    def _http_status_error(status_code: int, detail: str = "") -> httpx.HTTPStatusError:
        """Build an ``HTTPStatusError`` shaped the way ``api_get`` raises one."""
        request = httpx.Request("GET", "https://example.com/embed/jobs/x")
        response = httpx.Response(
            status_code,
            json={"detail": detail or f"HTTP {status_code}"},
            request=request,
        )
        return httpx.HTTPStatusError(detail or f"HTTP {status_code}", request=request, response=response)

    def test_poll_returns_result_on_success(self):
        """Happy path: terminal succeeded → result returned."""
        from client.app.content.tools.tabs import split_embed as mod

        responses = [
            {"status": "running", "progress": {"stage": "embedding"}},
            {"status": "succeeded", "result": {"total_chunks": 7}},
        ]
        with (
            patch.object(mod, "api_get", side_effect=responses),
            patch.object(mod.time, "sleep"),
        ):
            result = mod._poll_embed_job("job-1", {"client": "x"})
        assert result == {"total_chunks": 7}

    def test_poll_raises_on_failed_status(self):
        """Terminal failed → raise an httpx.HTTPStatusError with the detail."""
        from client.app.content.tools.tabs import split_embed as mod

        responses = [{"status": "failed", "error": "embedding model offline"}]
        with (
            patch.object(mod, "api_get", side_effect=responses),
            patch.object(mod.time, "sleep"),
            pytest.raises(httpx.HTTPStatusError) as excinfo,
        ):
            mod._poll_embed_job("job-1", {"client": "x"})
        assert "embedding model offline" in str(excinfo.value)

    def test_poll_tolerates_transient_503(self):
        """A transient 503 must not abort the loop.

        The status endpoint returns 503 when CORE is briefly unavailable
        for cross-replica state tracking. The pipeline itself is still
        running — clients should back off and keep polling instead of
        treating 503 as a terminal error.
        """
        from client.app.content.tools.tabs import split_embed as mod

        # Sequence: running, 503 blip, running, succeeded
        scripted = [
            {"status": "running", "progress": {"stage": "embedding"}},
            self._http_status_error(503, "CORE unavailable"),
            {"status": "running", "progress": {"stage": "embedding"}},
            {"status": "succeeded", "result": {"total_chunks": 3}},
        ]

        def _mocked_api_get(*_args, **_kwargs):
            value = scripted.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value

        with (
            patch.object(mod, "api_get", side_effect=_mocked_api_get),
            patch.object(mod.time, "sleep"),
        ):
            result = mod._poll_embed_job("job-1", {"client": "x"})

        assert result == {"total_chunks": 3}
        # All scripted responses were consumed — the loop kept polling
        # past the 503 instead of bailing out.
        assert scripted == []

    def test_poll_other_http_errors_propagate(self):
        """Non-503 HTTP errors are not retried — they surface immediately.

        A 401 / 404 means something structural is wrong (auth, bad job
        id) and retrying would just spin. Only 503 ("retry once CORE
        recovers") is special-cased.
        """
        from client.app.content.tools.tabs import split_embed as mod

        with (
            patch.object(mod, "api_get", side_effect=self._http_status_error(404, "no such job")),
            patch.object(mod.time, "sleep"),
            pytest.raises(httpx.HTTPStatusError) as excinfo,
        ):
            mod._poll_embed_job("job-1", {"client": "x"})
        assert excinfo.value.response.status_code == 404

    def test_poll_gives_up_on_persistent_503_outage(self):
        """A long-running 503 outage eventually surfaces an error.

        We don't want the UI to spin forever if CORE never comes back.
        After enough consecutive 503s the loop bails with a clear
        error so the user can see something is wrong.
        """
        from client.app.content.tools.tabs import split_embed as mod

        outage = self._http_status_error(503, "CORE down")

        def _always_503(*_args, **_kwargs):
            raise outage

        with (
            patch.object(mod, "api_get", side_effect=_always_503),
            patch.object(mod.time, "sleep"),
            pytest.raises(httpx.HTTPStatusError) as excinfo,
        ):
            mod._poll_embed_job("job-1", {"client": "x"})
        assert excinfo.value.response.status_code == 503

    def test_poll_tolerates_transient_transport_errors(self):
        """[P2] httpx transport-level failures must be retried, not propagated.

        ``api_get`` raises ``httpx.TimeoutException`` /
        ``httpx.TransportError`` (no HTTP response received) when the
        request itself times out or hits a network blip. These are
        not ``HTTPStatusError`` instances, so the existing 503 catch
        does not apply — without an explicit retry path the poll
        loop would exit and the outer UI handler wouldn't catch it.
        The server-side job is still running, so treat these like
        503s and back off.
        """
        from client.app.content.tools.tabs import split_embed as mod

        request = httpx.Request("GET", "https://example.com/embed/jobs/x")
        scripted = [
            {"status": "running", "progress": {"stage": "embedding"}},
            httpx.ReadTimeout("read timed out", request=request),
            httpx.ConnectError("connection refused", request=request),
            {"status": "running", "progress": {"stage": "embedding"}},
            {"status": "succeeded", "result": {"total_chunks": 4}},
        ]

        def _mocked_api_get(*_args, **_kwargs):
            value = scripted.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value

        with (
            patch.object(mod, "api_get", side_effect=_mocked_api_get),
            patch.object(mod.time, "sleep"),
        ):
            result = mod._poll_embed_job("job-1", {"client": "x"})

        assert result == {"total_chunks": 4}
        assert scripted == [], "loop did not consume all scripted responses"

    def test_poll_gives_up_on_persistent_transport_outage(self):
        """[P2] A long-running transport outage surfaces as ``HTTPStatusError``.

        Mirrors ``test_poll_gives_up_on_persistent_503_outage``: we
        cap the consecutive transient-failure budget so the UI does
        not spin forever when the server is genuinely unreachable.

        Crucially the *exhausted* path must surface as
        ``httpx.HTTPStatusError`` rather than a raw
        ``TransportError`` — the populate-request UI only catches
        ``HTTPStatusError`` (it then runs ``helpers.extract_error_detail``
        for the message), so a sustained transport outage would
        otherwise bypass the normal error display and bubble up as
        an uncaught Streamlit exception. The original transport
        error is preserved as ``__cause__`` for diagnostics.
        """
        from client.app.content.tools.tabs import split_embed as mod

        request = httpx.Request("GET", "https://example.com/embed/jobs/x")
        outage = httpx.ReadTimeout("read timed out", request=request)

        def _always_timeout(*_args, **_kwargs):
            raise outage

        with (
            patch.object(mod, "api_get", side_effect=_always_timeout),
            patch.object(mod.time, "sleep"),
            pytest.raises(httpx.HTTPStatusError) as excinfo,
        ):
            mod._poll_embed_job("job-1", {"client": "x"})
        # Synthesised as a 503 — same family as a CORE-unavailable
        # response, so existing UI paths treat it the same way.
        assert excinfo.value.response.status_code == 503
        # The detail must mention the transport failure so the user
        # gets actionable context, not a generic 503.
        detail = excinfo.value.response.json().get("detail", "")
        assert "ReadTimeout" in detail or "transport" in detail.lower(), (
            f"transport-exhaust 503 detail should mention the underlying failure; got {detail!r}"
        )
        # Original transport error preserved for diagnostic logging.
        assert isinstance(excinfo.value.__cause__, httpx.TransportError)

    def test_process_populate_request_marks_seen_active_on_202(self):
        """[P2] The submit-time mark must fire when the POST returns 202,
        passing the accepted job_id so the panel's seen set tracks
        this specific submission.

        If the user navigates to a panel-less page after submitting
        but before the fragment ever ticks, the seen set is the only
        thing that lets the panel detect the off-page completion on
        return. Tracking by job_id (not just a boolean) lets the
        panel distinguish concurrent submissions and refresh on each
        independent completion.
        """
        from client.app.content.tools.tabs import split_embed as mod

        mark_calls: list[str] = []

        def _capturing_api_post(path, **kwargs):  # noqa: ARG001
            if path == "embed/":
                return {"job_id": "j1", "status": "queued"}
            return {}

        source_data = mod.FileSourceData(
            file_source="SQL",
            sql_query="SELECT 1 FROM dual",
            sql_db_alias="TESTDB",
        )
        embed_config = {
            "alias": "vs",
            "model_key": "openai/text-embedding-3-small",
            "chunk_size": 1000,
            "chunk_overlap": 100,
            "distance_strategy": "COSINE",
            "index_type": "HNSW",
            "parsing_mode": "fast",
        }

        with (
            patch.object(mod, "api_post", side_effect=_capturing_api_post),
            patch.object(mod, "_poll_embed_job", return_value={"total_chunks": 0}),
            patch.object(
                mod,
                "mark_embed_job_started",
                side_effect=mark_calls.append,
            ),
            patch.object(
                mod,
                "state",
                MagicMock(
                    optimizer_client="x",
                    __getitem__=lambda *_a, **_k: {
                        "client_settings": {"oci": {"auth_profile": "p"}},
                    },
                ),
            ),
        ):
            result = mod._process_populate_request(embed_config, source_data, rate_limit=0)

        assert mark_calls == ["j1"], (
            f"mark_embed_job_started must be called exactly once with the accepted job_id; got {mark_calls!r}"
        )
        # Returned tuple lets the caller pass the id to the success
        # handler without round-tripping through session state.
        assert result == ("j1", {"total_chunks": 0})

    def test_handle_refresh_success_does_not_clear_seen_set(self, mock_st):
        """[P2] The OCI refresh path is synchronous and does NOT add
        anything to the seen set. ``_handle_refresh_success`` must
        therefore not call ``clear_embed_job_flag`` — doing so would
        wipe tracking for unrelated populate jobs that are concurrently
        in flight, breaking the auto-refresh guarantee for them.
        """
        from client.app.content.tools.tabs import split_embed as mod

        clear_calls: list = []
        with (
            patch.object(mod.helpers, "refresh_settings", return_value=True),
            patch.object(
                mod,
                "clear_embed_job_flag",
                side_effect=lambda *a: clear_calls.append(a),
            ),
            patch.object(mod, "st", mock_st),
        ):
            mod._handle_refresh_success({"new_files": 1, "updated_files": 0, "total_chunks_in_store": 5})
        assert clear_calls == [], (
            "_handle_refresh_success must not touch the seen set — the "
            "refresh path doesn't add anything to it, so clearing only "
            "harms unrelated tracked jobs"
        )

    def test_populate_failure_clears_specific_job_id_before_st_error(self, mock_st):
        """[P2] On a definitively terminal failure (non-503), only the
        failing job's id must be removed from the seen set, and the
        clear must precede ``st.error`` so the next fragment tick
        does not refresh-and-rerun, erasing the error message.
        """
        from client.app.content.tools.tabs import split_embed as mod

        order: list[str] = []
        clear_calls: list = []

        def _failing_populate(*_a, **_kw):
            order.append("populate_raises")
            ex = self._http_status_error(500, "boom")
            ex.job_id = "j-failing"  # type: ignore[attr-defined]
            raise ex

        with (
            patch.object(mod, "st", mock_st),
            patch.object(
                mod,
                "_render_population_button",
                return_value=(True, False),
            ),
            patch.object(mod, "_process_populate_request", side_effect=_failing_populate),
            patch.object(
                mod,
                "clear_embed_job_flag",
                side_effect=lambda *args: (
                    clear_calls.append(args),
                    order.append("clear"),
                ),
            ),
        ):
            mock_st.error.side_effect = lambda *a, **k: order.append("st_error")  # noqa: ARG005
            mod._handle_vector_store_population(
                embed_config={},
                source_data=mod.FileSourceData(file_source="SQL"),
                rate_limit=0,
                create_new_vs=True,
            )
        assert clear_calls == [("j-failing",)]
        assert order.index("clear") < order.index("st_error")

    def test_populate_503_preserves_seen_set_entry(self, mock_st):
        """[P2] 503 = "retry budget exhausted; the job may still be
        running server-side". The seen-set entry must be preserved so
        the eventual active->idle disappearance still triggers a refresh.
        """
        from client.app.content.tools.tabs import split_embed as mod

        clear_calls: list = []

        def _failing_populate(*_a, **_kw):
            ex = self._http_status_error(503, "Lost contact")
            ex.job_id = "j-pending"  # type: ignore[attr-defined]
            raise ex

        with (
            patch.object(mod, "st", mock_st),
            patch.object(
                mod,
                "_render_population_button",
                return_value=(True, False),
            ),
            patch.object(mod, "_process_populate_request", side_effect=_failing_populate),
            patch.object(
                mod,
                "clear_embed_job_flag",
                side_effect=lambda *a: clear_calls.append(a),
            ),
        ):
            mod._handle_vector_store_population(
                embed_config={},
                source_data=mod.FileSourceData(file_source="SQL"),
                rate_limit=0,
                create_new_vs=True,
            )
        assert clear_calls == []
        mock_st.error.assert_called_once()

    def test_pre_202_failure_does_not_clear_unrelated_jobs(self, mock_st):
        """[P2] A pre-POST failure (e.g. file-upload step raises) has no
        attached ``job_id`` — nothing was added to the seen set, so
        ``clear_embed_job_flag`` must not be called. Otherwise it
        would drop tracking for unrelated concurrent submissions.
        """
        from client.app.content.tools.tabs import split_embed as mod

        clear_calls: list = []

        def _early_failing_populate(*_a, **_kw):
            # No job_id attached — failure happened before submission.
            raise self._http_status_error(500, "upload fail")

        with (
            patch.object(mod, "st", mock_st),
            patch.object(
                mod,
                "_render_population_button",
                return_value=(True, False),
            ),
            patch.object(mod, "_process_populate_request", side_effect=_early_failing_populate),
            patch.object(
                mod,
                "clear_embed_job_flag",
                side_effect=lambda *a: clear_calls.append(a),
            ),
        ):
            mod._handle_vector_store_population(
                embed_config={},
                source_data=mod.FileSourceData(file_source="SQL"),
                rate_limit=0,
                create_new_vs=True,
            )
        assert clear_calls == []
        mock_st.error.assert_called_once()

    def test_handle_populate_success_clears_only_completed_job_id(self, mock_st):
        """[P2] On success, ``clear_embed_job_flag`` is called with the
        specific completed job_id (never a no-arg whole-set clear) AFTER
        a confirmed-successful refresh. A refresh failure must leave
        the seen-set entry intact for retry.
        """
        from client.app.content.tools.tabs import split_embed as mod

        order: list[str] = []
        clear_calls: list = []

        with (
            patch.object(
                mod.helpers,
                "refresh_settings",
                side_effect=lambda *a, **k: order.append("refresh") or True,  # noqa: ARG005
            ),
            patch.object(
                mod,
                "clear_embed_job_flag",
                side_effect=lambda *args: (
                    clear_calls.append(args),
                    order.append("clear"),
                ),
            ),
            patch.object(mod, "st", mock_st),
        ):
            mod._handle_populate_success("j-completed", {"message": "ok", "total_chunks": 0})

        assert order == ["refresh", "clear"]
        assert clear_calls == [("j-completed",)]

    def test_handle_populate_success_keeps_flag_when_refresh_fails(self, mock_st):
        """[P2] When ``refresh_settings`` returns False (server briefly
        down), the seen-set entry must NOT be cleared — the panel needs
        it to retry on the next 2-second tick.
        """
        from client.app.content.tools.tabs import split_embed as mod

        clear_calls: list = []
        with (
            patch.object(mod.helpers, "refresh_settings", return_value=False),
            patch.object(
                mod,
                "clear_embed_job_flag",
                side_effect=lambda *a: clear_calls.append(a),
            ),
            patch.object(mod, "st", mock_st),
        ):
            mod._handle_populate_success("j-completed", {"message": "ok", "total_chunks": 0})

        assert clear_calls == []

    def test_process_populate_request_uses_long_acceptance_timeout(self):
        """[P2] The 202 acceptance request must tolerate slow-server cases.

        Reviewer concern: the server's POST /v1/embed/ can sit on
        ``_settings_lock`` waiting on a slow ``update_database``, or
        on a slow CORE INSERT, before returning the 202 with the
        job id. If ``api_post`` here times out at 30s while the
        request handler still completes ``manager.submit`` and
        starts the background task, the user has no job_id to poll
        — the job runs invisibly and the UI cannot recover. The
        acceptance timeout has to outlast the realistic worst-case
        pre-202 latency (lock contention with a slow connection
        test, or a CORE blip during INSERT). 30s is too short.
        """
        from client.app.content.tools.tabs import split_embed as mod

        captured_calls: list[tuple[str, dict]] = []

        def _capturing_api_post(path, **kwargs):
            captured_calls.append((path, kwargs))
            if path == "embed/":
                return {"job_id": "synthetic", "status": "queued"}
            return {}

        # Drive ``_process_populate_request`` through the SQL branch
        # because it's the simplest path that exercises the embed
        # acceptance request — Local would require a fake uploader.
        source_data = mod.FileSourceData(
            file_source="SQL",
            sql_query="SELECT 1 FROM dual",
            sql_db_alias="TESTDB",
        )
        embed_config = {
            "alias": "vs",
            "model_key": "openai/text-embedding-3-small",
            "chunk_size": 1000,
            "chunk_overlap": 100,
            "distance_strategy": "COSINE",
            "index_type": "HNSW",
            "parsing_mode": "fast",
        }

        with (
            patch.object(mod, "api_post", side_effect=_capturing_api_post),
            patch.object(
                mod,
                "_poll_embed_job",
                return_value={"total_chunks": 0},
            ),
            patch.object(
                mod,
                "state",
                MagicMock(
                    optimizer_client="x",
                    __getitem__=lambda *_a, **_k: {
                        "client_settings": {"oci": {"auth_profile": "p"}},
                    },
                ),
            ),
        ):
            mod._process_populate_request(embed_config, source_data, rate_limit=0)

        # Find the embed/ acceptance call and inspect its timeout.
        embed_calls = [kwargs for path, kwargs in captured_calls if path == "embed/"]
        assert embed_calls, "_process_populate_request did not POST embed/"
        accepted_timeout = embed_calls[0].get("timeout")
        assert accepted_timeout is not None and accepted_timeout >= 120, (
            f"acceptance request timeout was {accepted_timeout}s; that is "
            f"too short to outlast realistic pre-202 latency (slow "
            f"connection test under _settings_lock, slow CORE insert), "
            f"and the user can lose the job_id to ReadTimeout while the "
            f"server still completes the submission"
        )

    @pytest.fixture
    def oci_populate_env(self):
        """Standard mock setup for ``_process_populate_request`` OCI tests.

        Yields ``(mod, captured_calls, embed_config)``. ``captured_calls``
        is a list of ``(path, kwargs)`` tuples populated by the mocked
        ``api_post``; ``embed_config`` is the canonical request payload
        the four OCI tests share.
        """
        from client.app.content.tools.tabs import split_embed as mod

        captured_calls: list[tuple[str, dict]] = []

        def _capturing_api_post(path, **kwargs):
            captured_calls.append((path, kwargs))
            return {"job_id": "j-oci", "status": "queued"}

        embed_config = {
            "alias": "vs",
            "model_key": "openai/text-embedding-3-small",
            "chunk_size": 1000,
            "chunk_overlap": 100,
            "distance_strategy": "COSINE",
            "index_type": "HNSW",
            "parsing_mode": "fast",
        }

        with (
            patch.object(mod, "api_post", side_effect=_capturing_api_post),
            patch.object(mod, "_poll_embed_job", return_value={"total_chunks": 0}),
            patch.object(mod, "mark_embed_job_started"),
            patch.object(
                mod,
                "state",
                MagicMock(
                    optimizer_client="x",
                    __getitem__=lambda *_a, **_k: {
                        "client_settings": {"oci": {"auth_profile": "DEFAULT"}},
                    },
                ),
            ),
        ):
            yield mod, captured_calls, embed_config

    def test_oci_all_files_routes_to_single_endpoint_without_objects(self, oci_populate_env):
        """[P2] OCI bucket-wide mode must POST to ``embed/oci/store`` with no
        ``objects`` key — the server treats absent/empty as "embed every
        supported file in the bucket". It must NOT call the legacy
        two-step ``oci/objects/download`` + ``embed/`` endpoints, and the
        bucket name and auth_profile must travel in the JSON body.
        """
        mod, captured_calls, embed_config = oci_populate_env
        source_data = mod.FileSourceData(
            file_source="OCI",
            oci_bucket="docs",
            oci_all_files=True,
        )
        mod._process_populate_request(embed_config, source_data, rate_limit=0)

        paths = [path for path, _ in captured_calls]
        assert paths == ["embed/oci/store"], (
            f"OCI bucket-wide mode must POST only to embed/oci/store, not the legacy two-step path; got {paths!r}"
        )
        body = captured_calls[0][1]["json"]
        assert body["bucket_name"] == "docs"
        assert body["auth_profile"] == "DEFAULT"
        assert "objects" not in body, (
            "Bucket-wide mode must omit ``objects`` so the server embeds every supported file; got: " + repr(body)
        )

    def test_oci_single_endpoint_uses_long_acceptance_timeout(self, oci_populate_env):
        """[P2] /embed/oci/store downloads bucket objects on the request
        thread *before* returning the 202/job_id. Reusing /embed/'s 300s
        timeout would let httpx ReadTimeout expire during the download
        phase for large or all-files OCI embeds, costing the user the
        job_id while the server keeps running. The acceptance timeout
        for this path must be sized for OCI download + acceptance —
        the same shape ``/embed/refresh`` already uses (7200s).
        """
        mod, captured_calls, embed_config = oci_populate_env
        source_data = mod.FileSourceData(
            file_source="OCI",
            oci_bucket="docs",
            oci_all_files=True,
        )
        mod._process_populate_request(embed_config, source_data, rate_limit=0)

        oci_calls = [kwargs for path, kwargs in captured_calls if path == "embed/oci/store"]
        assert oci_calls, "_process_populate_request did not POST embed/oci/store"
        accepted_timeout = oci_calls[0].get("timeout")
        # Floor chosen to outlast a realistic large-bucket download
        # (many hundreds of MB to a few GB). 1800s is conservative; the
        # actual value should match the ``/embed/refresh`` precedent
        # (7200s) which has the same synchronous-download shape.
        assert accepted_timeout is not None and accepted_timeout >= 1800, (
            f"OCI acceptance timeout was {accepted_timeout}s; that is "
            f"too short to outlast bucket-download + acceptance. The "
            f"server downloads every requested object on the request "
            f"thread before returning the 202, so the client must "
            f"allow at least as much time as ``/embed/refresh`` (7200s)"
        )

    def test_oci_per_file_mode_with_zero_selections_does_not_post(self, oci_populate_env):
        """[P2] Per-file OCI mode with zero checked rows must not POST.

        The server treats omitted OR empty ``objects`` as "embed every
        supported file in the bucket". Without a client-side guard, a
        race that lets the button click through with zero rows checked
        would silently turn into a bucket-wide embed — the user thinks
        they submitted nothing but the server embeds the entire bucket.

        Match the existing ``oci_files_selected is None`` early-return
        contract: return ``(None, {})`` and skip the POST entirely.
        """
        mod, captured_calls, embed_config = oci_populate_env
        df = pd.DataFrame({"File": ["a.pdf", "b.pdf"], "Process": [False, False]})
        source_data = mod.FileSourceData(
            file_source="OCI",
            oci_bucket="docs",
            oci_files_selected=df,
            oci_all_files=False,
        )
        result = mod._process_populate_request(embed_config, source_data, rate_limit=0)

        assert captured_calls == [], (
            "Per-file mode with zero selections must NOT POST — the server "
            "would interpret an empty ``objects`` list as a bucket-wide "
            f"embed; got POST(s): {captured_calls!r}"
        )
        assert result == (None, {}), (
            f"Expected the same (None, {{}}) early-return contract used for the None DataFrame case; got {result!r}"
        )

    def test_oci_selected_files_routes_to_single_endpoint_with_objects(self, oci_populate_env):
        """[P2] OCI per-file mode must POST to ``embed/oci/store`` with
        only the checked files in ``objects``. Unchecked rows must be
        excluded so the server does not embed unwanted bucket contents.
        """
        mod, captured_calls, embed_config = oci_populate_env
        df = pd.DataFrame({"File": ["keep.pdf", "skip.pdf", "also-keep.txt"], "Process": [True, False, True]})
        source_data = mod.FileSourceData(
            file_source="OCI",
            oci_bucket="docs",
            oci_files_selected=df,
            oci_all_files=False,
        )
        mod._process_populate_request(embed_config, source_data, rate_limit=0)

        assert [path for path, _ in captured_calls] == ["embed/oci/store"]
        body = captured_calls[0][1]["json"]
        assert body["objects"] == ["keep.pdf", "also-keep.txt"]

    def test_poll_emits_progress_toast_on_stage_change(self):
        """[P3] Each new (stage, message) progress reading must reach Streamlit.

        Pre-fix the loop only logged stage changes to LOGGER.debug, so
        users saw the static spinner with no indication of pipeline
        progress despite the new polling/progress plumbing on the
        server. Surface progress to Streamlit so each stage is
        actually visible.
        """
        from client.app.content.tools.tabs import split_embed as mod

        responses = [
            {"status": "running", "progress": {"stage": "splitting", "message": "Parsing"}},
            {"status": "running", "progress": {"stage": "embedding", "message": "Embedding chunks"}},
            {"status": "running", "progress": {"stage": "finalizing"}},
            {"status": "succeeded", "result": {"total_chunks": 5}},
        ]

        with (
            patch.object(mod, "api_get", side_effect=responses),
            patch.object(mod.time, "sleep"),
            patch.object(mod.st, "toast") as mock_toast,
        ):
            result = mod._poll_embed_job("job-1", {"client": "x"})

        assert result == {"total_chunks": 5}
        # At least one call per distinct progress message — duplicates
        # would still fail the contract because each new stage must
        # be visible to the user.
        assert mock_toast.call_count >= 3, (
            f"expected progress toast for each stage change; st.toast was called {mock_toast.call_count} time(s)"
        )
        # Sanity-check the rendered text includes the user-facing
        # stage labels rather than raw stage codes.
        rendered_calls = [str(c.args[0]) for c in mock_toast.call_args_list]
        assert any("Parsing" in r or "Parsing & chunking" in r for r in rendered_calls), (
            f"splitting-stage toast missing or unrendered: {rendered_calls}"
        )
        assert any("Embedding" in r for r in rendered_calls), f"embedding-stage toast missing: {rendered_calls}"


class TestActiveEmbedJobsPanelWiring:
    """The embedding tab must show the active-embed-jobs panel so a
    user who navigates away mid-job and returns still sees progress.

    Placement contract: rendered AFTER the Populate Vector Store
    section so the panel appears below it.

    Idle contract: hidden entirely when no jobs are running
    (``hide_when_idle=True``) so users in the workflow context don't
    see an empty banner.

    Refresh contract: ``refresh_on_idle=True``. The synchronous
    populate path already calls ``helpers.refresh_settings`` on
    success, but a user who starts a job and then navigates away
    mid-flight (which kills the synchronous polling loop) and
    returns relies on the fragment as the only completion observer.
    Without ``refresh_on_idle``, the fragment would hide the panel
    on completion and ``state.settings`` would stay stale until the
    user manually refreshed or visited another tab.
    """

    def test_display_split_embed_renders_panel_after_populate_section(self):
        """display_split_embed calls render_active_embed_jobs after the
        populate section, with hide_when_idle=True AND refresh_on_idle=True
        so a navigate-away-and-back completion still refreshes state.
        """
        MODULE = "client.app.content.tools.tabs.split_embed"
        call_order: list[str] = []

        def _record(name):
            def _inner(*args, **kwargs):  # noqa: ARG001
                call_order.append(name)

            return _inner

        with (
            patch(
                f"{MODULE}.render_active_embed_jobs",
                side_effect=_record("panel"),
            ) as mock_render,
            patch(
                f"{MODULE}._initialize_and_validate_config",
                return_value=({}, [], None),
            ),
            patch(
                f"{MODULE}._configure_vector_store_mode",
                return_value=(True, {}),  # empty embed_config skips populate handler
            ),
            patch(
                f"{MODULE}._render_load_kb_section",
                side_effect=_record("load_kb"),
            ),
            patch(
                f"{MODULE}._render_populate_vs_section",
                side_effect=_record("populate"),
            ),
            patch(
                f"{MODULE}._handle_vector_store_population",
                side_effect=_record("populate_button"),
            ),
        ):
            from client.app.content.tools.tabs.split_embed import display_split_embed

            display_split_embed()
        # Panel renders AFTER the populate section so users see it
        # below "Populate Vector Store".
        assert call_order == ["load_kb", "populate", "panel"], f"panel must follow populate section; got {call_order}"
        mock_render.assert_called_once_with(refresh_on_idle=True, hide_when_idle=True)


class TestOciSourceLockMatrix:
    """Lock matrix for AIO_OCI_SOURCE_BUCKET_* env vars in _render_load_kb_section.

    The compartment env is the anchor: when unset or unresolved, the bucket env
    is ignored regardless of value. When the compartment resolves, the
    compartment selectbox is pinned + disabled; the bucket selectbox is pinned
    only when the env-named bucket also exists in the pinned compartment.
    Auth state is never consulted.
    """

    PINNED_COMPARTMENT_LABEL = "Pinned"
    PINNED_COMPARTMENT_OCID = "ocid1.compartment.oc1..pinned"
    OTHER_COMPARTMENT_LABEL = "Other"
    OTHER_COMPARTMENT_OCID = "ocid1.compartment.oc1..other"
    PINNED_BUCKET = "pinned-bucket"
    OTHER_BUCKET = "other-bucket"

    def _compartments(self):
        return {
            self.PINNED_COMPARTMENT_LABEL: self.PINNED_COMPARTMENT_OCID,
            self.OTHER_COMPARTMENT_LABEL: self.OTHER_COMPARTMENT_OCID,
        }

    def _run_render(
        self,
        monkeypatch,
        mock_st,
        *,
        compartment_env=None,
        bucket_env=None,
        compartments=None,
        bucket_list_for_pinned=None,
    ):
        """Drive _render_load_kb_section with controlled env + OCI fixtures.

        Returns the list of st.selectbox call kwargs (one per call) so tests
        can assert on options/index/disabled.
        """
        from client.app.content.tools.tabs import split_embed

        monkeypatch.setattr(split_embed.client_settings, "oci_source_bucket_compartment_id", compartment_env)
        monkeypatch.setattr(split_embed.client_settings, "oci_source_bucket_name", bucket_env)

        compartments = compartments if compartments is not None else self._compartments()
        bucket_list_for_pinned = (
            bucket_list_for_pinned if bucket_list_for_pinned is not None else [self.PINNED_BUCKET, self.OTHER_BUCKET]
        )

        # Only the pinned compartment returns the configured bucket list, so
        # tests can verify bucket resolution scopes to the pinned compartment.
        def _get_buckets(compartment_ocid, _auth_profile):
            if compartment_ocid == self.PINNED_COMPARTMENT_OCID:
                return list(bucket_list_for_pinned)
            return []

        def _selectbox(_label, options, **kwargs):
            options_list = list(options)
            index = kwargs.get("index")
            if index is None or not options_list:
                return None
            return options_list[index]

        mock_st.selectbox.side_effect = _selectbox
        mock_st.radio.return_value = "OCI"
        mock_st.toggle.return_value = True

        from client.tests.conftest import AttrDict

        state_dict = AttrDict(
            {
                "settings": {
                    "client_settings": {"oci": {"auth_profile": "DEFAULT"}},
                },
                "optimizer_help": {"embed_supported_file_types": ""},
            }
        )

        with (
            patch.object(split_embed, "st", mock_st),
            patch.object(split_embed, "state", state_dict),
            patch.object(split_embed, "_get_compartments", return_value=compartments),
            patch.object(split_embed, "_get_buckets", side_effect=_get_buckets),
        ):
            split_embed._render_load_kb_section(
                file_sources=["OCI"],
                oci_setup={"namespace": "test-ns", "tenancy": "test-tenancy"},
            )

        return mock_st.selectbox.call_args_list

    def _compartment_call(self, calls):
        for call in calls:
            args, kwargs = call
            label = args[0] if args else kwargs.get("label")
            if label == "Bucket compartment:":
                return args, kwargs
        raise AssertionError("Bucket compartment selectbox was not rendered")

    def _bucket_call(self, calls):
        for call in calls:
            args, kwargs = call
            label = args[0] if args else kwargs.get("label")
            if label == "Source bucket:":
                return args, kwargs
        raise AssertionError("Source bucket selectbox was not rendered")

    def test_no_env_vars_both_selectboxes_free(self, monkeypatch, mock_st):
        """No env vars → both selectboxes editable, full compartment list."""
        calls = self._run_render(monkeypatch, mock_st)

        comp_args, comp_kwargs = self._compartment_call(calls)
        assert list(comp_args[1]) == list(self._compartments().keys())
        assert comp_kwargs.get("index") is None
        assert comp_kwargs.get("disabled") is not True

        bucket_args, bucket_kwargs = self._bucket_call(calls)
        # Without a compartment chosen, bucket options are an empty list and
        # the widget is disabled solely because no compartment is selected.
        assert list(bucket_args[1]) == []
        assert bucket_kwargs.get("index") is None
        assert bucket_kwargs.get("disabled") is True

    def test_bucket_only_env_is_ignored(self, monkeypatch, mock_st):
        """Bucket env set without compartment env → bucket env ignored entirely."""
        calls = self._run_render(monkeypatch, mock_st, bucket_env=self.PINNED_BUCKET)

        comp_args, comp_kwargs = self._compartment_call(calls)
        # Full compartment list, no pre-selection, editable — identical to the
        # no-env-vars case.
        assert list(comp_args[1]) == list(self._compartments().keys())
        assert comp_kwargs.get("index") is None
        assert comp_kwargs.get("disabled") is not True

        # The bucket selectbox is empty because no compartment is chosen, and
        # crucially is NOT pre-selected to the env value or disabled by the lock.
        _, bucket_kwargs = self._bucket_call(calls)
        assert bucket_kwargs.get("index") is None

    def test_compartment_only_locks_compartment_and_scopes_bucket(self, monkeypatch, mock_st):
        """Compartment env resolves → compartment locked; bucket free within it."""
        calls = self._run_render(
            monkeypatch,
            mock_st,
            compartment_env=self.PINNED_COMPARTMENT_OCID,
        )

        comp_args, comp_kwargs = self._compartment_call(calls)
        # Compartment dropdown collapses to a single option (the resolved
        # label) and is disabled.
        assert list(comp_args[1]) == [self.PINNED_COMPARTMENT_LABEL]
        assert comp_kwargs.get("index") == 0
        assert comp_kwargs.get("disabled") is True

        bucket_args, bucket_kwargs = self._bucket_call(calls)
        # Bucket selectbox enumerates the pinned compartment's buckets and
        # leaves selection to the user.
        assert list(bucket_args[1]) == [self.PINNED_BUCKET, self.OTHER_BUCKET]
        assert bucket_kwargs.get("index") is None
        # disabled is driven by 'not bucket_compartment' alone here; the
        # compartment IS selected (pinned), so the bucket selectbox is
        # editable.
        assert bucket_kwargs.get("disabled") is False

    def test_both_env_resolve_locks_both(self, monkeypatch, mock_st):
        """Compartment + bucket envs both resolve → both selectboxes locked."""
        calls = self._run_render(
            monkeypatch,
            mock_st,
            compartment_env=self.PINNED_COMPARTMENT_OCID,
            bucket_env=self.PINNED_BUCKET,
        )

        comp_args, comp_kwargs = self._compartment_call(calls)
        assert list(comp_args[1]) == [self.PINNED_COMPARTMENT_LABEL]
        assert comp_kwargs.get("disabled") is True

        bucket_args, bucket_kwargs = self._bucket_call(calls)
        assert list(bucket_args[1]) == [self.PINNED_BUCKET]
        assert bucket_kwargs.get("index") == 0
        assert bucket_kwargs.get("disabled") is True

    def test_bucket_not_in_compartment_silent_bucket_fallback(self, monkeypatch, mock_st):
        """Bucket env not in pinned compartment → compartment locked, bucket free."""
        calls = self._run_render(
            monkeypatch,
            mock_st,
            compartment_env=self.PINNED_COMPARTMENT_OCID,
            bucket_env="non-existent-bucket",
        )

        _, comp_kwargs = self._compartment_call(calls)
        assert comp_kwargs.get("disabled") is True

        bucket_args, bucket_kwargs = self._bucket_call(calls)
        # Bucket falls back to the full pinned-compartment bucket list, no
        # pre-selection. The compartment selectbox returned the pinned label,
        # so the bucket widget is editable.
        assert list(bucket_args[1]) == [self.PINNED_BUCKET, self.OTHER_BUCKET]
        assert bucket_kwargs.get("index") is None
        assert bucket_kwargs.get("disabled") is False

    def test_compartment_unresolved_falls_back_completely(self, monkeypatch, mock_st):
        """Compartment OCID does not resolve → both selectboxes free; bucket env ignored."""
        calls = self._run_render(
            monkeypatch,
            mock_st,
            compartment_env="ocid1.compartment.oc1..does-not-exist",
            bucket_env=self.PINNED_BUCKET,
        )

        comp_args, comp_kwargs = self._compartment_call(calls)
        # Full compartment list, no lock — the unresolvable OCID silently
        # disables the entire lock.
        assert list(comp_args[1]) == list(self._compartments().keys())
        assert comp_kwargs.get("index") is None
        assert comp_kwargs.get("disabled") is not True

        # Bucket env is ignored when the compartment lock fails to engage.
        _, bucket_kwargs = self._bucket_call(calls)
        assert bucket_kwargs.get("index") is None
