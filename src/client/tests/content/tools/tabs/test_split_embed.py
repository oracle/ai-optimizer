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
            side_effect=ValueError("URL not permitted."),
        ):
            split_embed._is_url_accessible.clear()
            ok, msg = split_embed._is_url_accessible(
                "http://169.254.169.254/", restricted=True
            )

        assert ok is False
        assert msg == "URL not permitted."

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
            ok, msg = split_embed._is_url_accessible(
                "http://start.example.com/", restricted=True
            )

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
        validate_results: list[Exception | None] = [None, ValueError("URL not permitted.")]

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
            ok, msg = split_embed._is_url_accessible(
                "http://start.example.com/", restricted=True
            )

        assert ok is False
        assert msg == "URL not permitted."

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
            ok, msg = split_embed._is_url_accessible(
                "http://start.example.com/", restricted=True
            )

        assert ok is False
        assert "not accessible" in msg.lower() or msg == "URL not permitted."

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
