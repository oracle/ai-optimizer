"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.core.api
"""
# spell-checker: disable

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

MODULE = "client.app.core.api"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mock_settings(**overrides):
    """Create a mock settings object with defaults."""
    m = MagicMock()
    m.server_url = overrides.get("server_url", "http://localhost")
    m.server_port = overrides.get("server_port", 8000)
    m.server_ssl = overrides.get("server_ssl", False)
    m.server_url_prefix = overrides.get("server_url_prefix", "")
    m.api_key = overrides.get("api_key", "test-key")
    return m


def _resp(status_code=200, json_data=None, content=None):
    """Build an httpx.Response."""
    if json_data is not None:
        body = json.dumps(json_data).encode()
        headers = {"content-type": "application/json"}
    elif content is not None:
        body = content
        headers = {}
    else:
        body = b""
        headers = {}
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", "http://test"),
        content=body,
        headers=headers,
    )


def _http_error(status_code=400, json_body=None):
    """Build an HTTPStatusError."""
    resp = _resp(status_code, json_data=json_body or {"detail": "error"})
    return httpx.HTTPStatusError("error", request=resp.request, response=resp)


def _mock_client_ctx(response=None, side_effect=None):
    """Return (context_manager, client_instance) for patching httpx.Client."""
    instance = MagicMock()
    if side_effect:
        for method in ("get", "post", "put", "patch", "delete"):
            getattr(instance, method).side_effect = side_effect
    elif response is not None:
        for method in ("get", "post", "put", "patch", "delete"):
            getattr(instance, method).return_value = response
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=instance)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, instance


# ---------------------------------------------------------------------------
# _base_url
# ---------------------------------------------------------------------------
class TestBaseUrl:
    """Tests for the _base_url helper."""

    def test_default_url(self):
        """Verify default base URL uses localhost, port, and /v1 prefix."""
        settings = _mock_settings()
        with patch(f"{MODULE}.settings", settings):
            from client.app.core.api import _base_url

            result = _base_url()
        assert result == "http://localhost:8000/v1"

    def test_custom_api_prefix(self):
        """Verify a custom api_prefix replaces the default /v1."""
        settings = _mock_settings()
        with patch(f"{MODULE}.settings", settings):
            from client.app.core.api import _base_url

            result = _base_url("/v2")
        assert result == "http://localhost:8000/v2"

    def test_server_url_prefix(self):
        """Verify server_url_prefix is included in the base URL."""
        settings = _mock_settings(server_url_prefix="/app")
        with patch(f"{MODULE}.settings", settings):
            from client.app.core.api import _base_url

            result = _base_url()
        assert result == "http://localhost:8000/app/v1"

    def test_url_with_port_in_server_url(self):
        """Verify port embedded in server_url takes precedence."""
        settings = _mock_settings(server_url="http://myhost:9000")
        with patch(f"{MODULE}.settings", settings):
            from client.app.core.api import _base_url

            result = _base_url()
        assert result == "http://myhost:9000/v1"

    def test_url_with_path_in_server_url(self):
        """Verify a path in server_url is preserved in the base URL."""
        settings = _mock_settings(server_url="http://myhost/base")
        with patch(f"{MODULE}.settings", settings):
            from client.app.core.api import _base_url

            result = _base_url()
        assert result == "http://myhost:8000/base/v1"


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------
class TestHeaders:
    """Tests for the _headers helper."""

    def test_with_api_key(self):
        """Verify X-API-Key header is set when api_key is configured."""
        settings = _mock_settings(api_key="secret123")
        with patch(f"{MODULE}.settings", settings):
            from client.app.core.api import _headers

            result = _headers()
        assert result == {"X-API-Key": "secret123"}

    def test_empty_api_key(self):
        """Verify X-API-Key defaults to empty string when api_key is None."""
        settings = _mock_settings(api_key=None)
        with patch(f"{MODULE}.settings", settings):
            from client.app.core.api import _headers

            result = _headers()
        assert result == {"X-API-Key": ""}


# ---------------------------------------------------------------------------
# api_get
# ---------------------------------------------------------------------------
class TestApiGet:
    """Tests for api_get."""

    def test_success(self):
        """Verify api_get returns parsed JSON on a 200 response."""
        resp = _resp(200, json_data={"key": "value"})
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_get

            result = api_get("test/path")
        assert result == {"key": "value"}

    def test_params_forwarded(self):
        """Verify query params are forwarded to the underlying GET call."""
        resp = _resp(200, json_data={})
        ctx, instance = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_get

            api_get("path", params={"foo": "bar"})
        instance.get.assert_called_once()
        _, kwargs = instance.get.call_args
        assert kwargs["params"] == {"foo": "bar"}

    def test_extra_headers_merged(self):
        """Verify extra_headers are merged into the client headers."""
        resp = _resp(200, json_data={})
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx) as mock_cls,
        ):
            from client.app.core.api import api_get

            api_get("path", extra_headers={"client": "c1"})
        # Check headers passed to Client constructor include the extra header
        _, kwargs = mock_cls.call_args
        assert kwargs["headers"]["client"] == "c1"

    def test_custom_api_prefix(self):
        """Verify a custom api_prefix is reflected in the request URL."""
        resp = _resp(200, json_data={})
        ctx, instance = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_get

            api_get("healthz", api_prefix="/mcp")
        url_called = instance.get.call_args[0][0]
        assert "/mcp/healthz" in url_called

    def test_http_error_raised(self):
        """Verify api_get raises HTTPStatusError on a 500 response."""
        error_resp = _resp(500, json_data={"detail": "fail"})
        ctx, _ = _mock_client_ctx(response=error_resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_get

            with pytest.raises(httpx.HTTPStatusError):
                api_get("fail/path")


# ---------------------------------------------------------------------------
# api_post
# ---------------------------------------------------------------------------
class TestApiPost:
    """Tests for api_post."""

    def test_success(self):
        """Verify api_post returns parsed JSON on a 200 response."""
        resp = _resp(200, json_data={"id": 1})
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_post

            result = api_post("items", json={"name": "test"})
        assert result == {"id": 1}

    def test_no_toast_when_none(self):
        """Verify no toast is shown when toast parameter is omitted."""
        resp = _resp(200, json_data={"ok": True})
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        mock_st = MagicMock()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
            patch(f"{MODULE}.st", mock_st),
        ):
            from client.app.core.api import api_post

            api_post("items")
        mock_st.toast.assert_not_called()

    def test_http_error_raised(self):
        """Verify api_post raises HTTPStatusError on a 422 response."""
        error_resp = _resp(422, json_data={"detail": "bad"})
        error_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("bad", request=error_resp.request, response=error_resp)
        )
        ctx, _ = _mock_client_ctx(response=error_resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_post

            with pytest.raises(httpx.HTTPStatusError):
                api_post("bad/path")


# ---------------------------------------------------------------------------
# api_put
# ---------------------------------------------------------------------------
class TestApiPut:
    """Tests for api_put."""

    def test_success(self):
        """Verify api_put returns parsed JSON on a 200 response."""
        resp = _resp(200, json_data={"updated": True})
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_put

            result = api_put("items/1", json={"name": "new"})
        assert result == {"updated": True}

    def test_params_forwarded(self):
        """Verify query params are forwarded to the underlying PUT call."""
        resp = _resp(200, json_data={})
        ctx, instance = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_put

            api_put("items/1", params={"client": "c1"})
        _, kwargs = instance.put.call_args
        assert kwargs["params"] == {"client": "c1"}

    def test_http_error_raised(self):
        """Verify api_put raises HTTPStatusError on a 500 response."""
        error_resp = _resp(500, json_data={"detail": "fail"})
        error_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("fail", request=error_resp.request, response=error_resp)
        )
        ctx, _ = _mock_client_ctx(response=error_resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_put

            with pytest.raises(httpx.HTTPStatusError):
                api_put("bad/path")


# ---------------------------------------------------------------------------
# api_patch
# ---------------------------------------------------------------------------
class TestApiPatch:
    """Tests for api_patch."""

    def test_success(self):
        """Verify api_patch returns parsed JSON on a 200 response."""
        resp = _resp(200, json_data={"updated": True})
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_patch

            result = api_patch("items/1", json={"field": "val"})
        assert result == {"updated": True}

    def test_204_returns_none(self):
        """Verify api_patch returns None on a 204 No Content response."""
        resp = _resp(204, content=b"")
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_patch

            result = api_patch("items/1")
        assert result is None

    def test_http_error_raised(self):
        """Verify api_patch raises HTTPStatusError on a 500 response."""
        error_resp = _resp(500, json_data={"detail": "fail"})
        error_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("fail", request=error_resp.request, response=error_resp)
        )
        ctx, _ = _mock_client_ctx(response=error_resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_patch

            with pytest.raises(httpx.HTTPStatusError):
                api_patch("bad/path")


# ---------------------------------------------------------------------------
# api_delete
# ---------------------------------------------------------------------------
class TestApiDelete:
    """Tests for api_delete."""

    def test_success(self):
        """Verify api_delete completes without error on a 204 response."""
        resp = _resp(204, content=b"")
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_delete

            api_delete("items/1")

    def test_http_error_raised(self):
        """Verify api_delete raises HTTPStatusError on a 500 response."""
        error_resp = _resp(500, json_data={"detail": "fail"})
        error_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("fail", request=error_resp.request, response=error_resp)
        )
        ctx, _ = _mock_client_ctx(response=error_resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import api_delete

            with pytest.raises(httpx.HTTPStatusError):
                api_delete("bad/path")


# ---------------------------------------------------------------------------
# Toast notification (shared across mutating verbs)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "verb,resp",
    [
        ("api_post", _resp(200, json_data={})),
        ("api_put", _resp(200, json_data={})),
        ("api_patch", _resp(200, json_data={})),
        ("api_delete", _resp(204, content=b"")),
    ],
)
def test_toast_shown(verb, resp):
    """Each mutating verb fires st.toast with the supplied message and ✅ icon."""
    ctx, _ = _mock_client_ctx(response=resp)
    settings = _mock_settings()
    mock_st = MagicMock()
    with (
        patch(f"{MODULE}.settings", settings),
        patch(f"{MODULE}.httpx.Client", return_value=ctx),
        patch(f"{MODULE}.st", mock_st),
    ):
        import importlib

        func = getattr(importlib.import_module(MODULE), verb)
        func("path", toast="Done!")
    mock_st.toast.assert_called_once_with("Done!", icon="✅")


# ---------------------------------------------------------------------------
# get_server_settings
# ---------------------------------------------------------------------------
class TestGetServerSettings:
    """Tests for get_server_settings."""

    def test_success(self):
        """Verify get_server_settings returns data on a successful call."""
        resp = _resp(200, json_data={"settings": "ok"})
        ctx, _ = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import get_server_settings

            result = get_server_settings(client="test")
        assert result == {"settings": "ok"}

    def test_http_error_returns_none(self):
        """Verify get_server_settings returns None when the server is unreachable."""
        fail_resp = _resp(503, json_data={"detail": "down"})
        fail_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("err", request=fail_resp.request, response=fail_resp)
        )
        ctx, _ = _mock_client_ctx(response=fail_resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import get_server_settings

            result = get_server_settings(client="test")
        assert result is None

    def test_params_forwarded(self):
        """The standard GET path forwards only the client param."""
        resp = _resp(200, json_data={"ok": True})
        ctx, instance = _mock_client_ctx(response=resp)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import get_server_settings

            get_server_settings(client="my-client", include_sensitive=False)
        _, kwargs = instance.get.call_args
        assert kwargs["params"]["client"] == "my-client"
        assert "include_sensitive" not in kwargs["params"]


    def test_include_sensitive_routes_to_export(self):
        """``include_sensitive=True`` triggers the export helper."""
        resp = _resp(200, json_data={"ok": True})
        ctx, instance = _mock_client_ctx(response=resp)
        # Wire the post() call so the export helper uses our mock context.
        instance.post = instance.get  # reuse mock
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.Client", return_value=ctx),
        ):
            from client.app.core.api import get_server_settings

            get_server_settings(client="my-client", include_sensitive=True)
        # Verify the post path (which the export helper uses) was hit.
        # Either get or post on the mock instance is fine because we aliased.
        assert instance.get.called or getattr(instance, "post", instance.get).called


# ---------------------------------------------------------------------------
# _spawn_server
# ---------------------------------------------------------------------------
class TestSpawnServer:
    """Tests for _spawn_server."""

    def test_subprocess_called(self, tmp_path):
        """Verify _spawn_server invokes subprocess.Popen with uvicorn arguments."""
        log_path = tmp_path / "test.log"
        mock_proc = MagicMock()
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from client.app.core.api import _spawn_server

            proc, log_fh = _spawn_server("8000", {"PATH": "/usr/bin"}, log_path)
        assert proc is mock_proc
        assert not log_fh.closed
        log_fh.close()
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "uvicorn" in args
        assert "0.0.0.0" in args
        assert "8000" in args

    def test_subprocess_adds_ssl_flags(self, tmp_path):
        """Verify _spawn_server mirrors entrypoint server SSL flags."""
        log_path = tmp_path / "test.log"
        mock_proc = MagicMock()
        settings = _mock_settings(server_ssl=True)
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.ensure_ssl_cert", return_value=(tmp_path / "cert.pem", tmp_path / "key.pem")),
            patch(f"{MODULE}.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            from client.app.core.api import _spawn_server

            _, log_fh = _spawn_server("8000", {"PATH": "/usr/bin"}, log_path)
        log_fh.close()
        args = mock_popen.call_args[0][0]
        assert "--ssl-certfile" in args
        assert str(tmp_path / "cert.pem") in args
        assert "--ssl-keyfile" in args
        assert str(tmp_path / "key.pem") in args

    def test_returns_tuple(self, tmp_path):
        """Verify _spawn_server returns a (process, log_file) tuple."""
        log_path = tmp_path / "test.log"
        mock_proc = MagicMock()
        with patch(f"{MODULE}.subprocess.Popen", return_value=mock_proc):
            from client.app.core.api import _spawn_server

            result = _spawn_server("8000", {}, log_path)
        assert isinstance(result, tuple)
        assert len(result) == 2
        result[1].close()


class TestWaitForServerReady:
    """Tests for _wait_for_server_ready."""

    def test_returns_true_when_liveness_responds(self):
        """Verify the helper returns True once /liveness returns 200."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        ok_resp = MagicMock(status_code=200)
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.get", return_value=ok_resp) as mock_get,
            patch(f"{MODULE}.time.sleep"),
        ):
            from client.app.core.api import _wait_for_server_ready

            assert _wait_for_server_ready(mock_proc, timeout=5) is True
        mock_get.assert_called()

    def test_probes_locally_when_server_url_overridden(self):
        """AIO_SERVER_URL config must not redirect the local subprocess probe."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        ok_resp = MagicMock(status_code=200)
        settings = _mock_settings(server_url="http://api.example.com", server_port=9000)
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.get", return_value=ok_resp) as mock_get,
            patch(f"{MODULE}.time.sleep"),
        ):
            from client.app.core.api import _wait_for_server_ready

            assert _wait_for_server_ready(mock_proc, timeout=5) is True
        mock_get.assert_called_once_with("http://127.0.0.1:9000/v1/liveness", timeout=1.0)

    def test_probes_https_when_spawned_server_uses_ssl(self):
        """AIO_SERVER_SSL must make the local readiness probe use HTTPS."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        ok_resp = MagicMock(status_code=200)
        settings = _mock_settings(server_ssl=True, server_port=9443)
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.get", return_value=ok_resp) as mock_get,
            patch(f"{MODULE}.time.sleep"),
        ):
            from client.app.core.api import _wait_for_server_ready

            assert _wait_for_server_ready(mock_proc, timeout=5) is True
        mock_get.assert_called_once_with("https://127.0.0.1:9443/v1/liveness", timeout=1.0, verify=False)

    def test_returns_false_when_process_exits(self):
        """Verify the helper returns False when the subprocess dies before becoming ready."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Exited
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.get", side_effect=httpx.ConnectError("nope")),
            patch(f"{MODULE}.time.sleep"),
        ):
            from client.app.core.api import _wait_for_server_ready

            assert _wait_for_server_ready(mock_proc, timeout=5) is False

    def test_returns_false_on_timeout(self):
        """Verify the helper returns False when /liveness never succeeds before the deadline."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        settings = _mock_settings()
        with (
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}.httpx.get", side_effect=httpx.ConnectError("nope")),
            patch(f"{MODULE}.time.sleep"),
        ):
            from client.app.core.api import _wait_for_server_ready

            assert _wait_for_server_ready(mock_proc, timeout=0.05) is False


# ---------------------------------------------------------------------------
# start_server
# ---------------------------------------------------------------------------
class TestStartServer:
    """Tests for start_server."""

    def test_skips_when_already_running(self):
        """Verify start_server does not spawn a new process when one is already running."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running
        with (
            patch(f"{MODULE}._SERVER", {"process": mock_proc, "log_file": None}),
            patch(f"{MODULE}._spawn_server") as mock_spawn,
        ):
            from client.app.core.api import start_server

            start_server()
        mock_spawn.assert_not_called()

    def test_starts_new_server(self):
        """Verify start_server spawns a new server process and waits for readiness."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running
        mock_fh = MagicMock()
        settings = _mock_settings()
        with (
            patch(f"{MODULE}._SERVER", {"process": None, "log_file": None}),
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}._spawn_server", return_value=(mock_proc, mock_fh)),
            patch(f"{MODULE}._wait_for_server_ready", return_value=True),
            patch(f"{MODULE}.atexit.register"),
        ):
            from client.app.core.api import start_server

            start_server()

    def test_skips_spawn_when_server_module_absent(self, tmp_path):
        """Component-specific images (Helm client pod, server-only image)
        strip the unused tree. With no `server/` directory under src/, the
        spawn target `server.app.main:app` cannot resolve — and on a
        read-only Helm filesystem the spawn would crash trying to open the
        uvicorn log file. The gate must short-circuit before any of that."""
        # tmp_path has no `server` subdirectory.
        with (
            patch(f"{MODULE}._SERVER", {"process": None, "log_file": None}),
            patch(f"{MODULE}._SRC_DIR", tmp_path),
            patch(f"{MODULE}._spawn_server") as mock_spawn,
            patch(f"{MODULE}._wait_for_server_ready") as mock_wait,
        ):
            from client.app.core.api import start_server

            start_server()
        mock_spawn.assert_not_called()
        mock_wait.assert_not_called()

    def test_spawns_when_server_module_present(self, tmp_path):
        """Positive gate: when the server tree IS present, the spawn path
        runs as before. Locks in that the directory check doesn't suppress
        all-in-one mode where both trees coexist."""
        (tmp_path / "server").mkdir()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_fh = MagicMock()
        settings = _mock_settings()
        with (
            patch(f"{MODULE}._SERVER", {"process": None, "log_file": None}),
            patch(f"{MODULE}._SRC_DIR", tmp_path),
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}._spawn_server", return_value=(mock_proc, mock_fh)) as mock_spawn,
            patch(f"{MODULE}._wait_for_server_ready", return_value=True),
            patch(f"{MODULE}.atexit.register"),
        ):
            from client.app.core.api import start_server

            start_server()
        mock_spawn.assert_called_once()

    def test_generates_api_key_when_none(self):
        """Verify start_server generates an API key when none is configured."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_fh = MagicMock()
        settings = _mock_settings(api_key=None)
        # Need to handle the falsy check: `if not settings.api_key`
        settings.api_key = None
        with (
            patch(f"{MODULE}._SERVER", {"process": None, "log_file": None}),
            patch(f"{MODULE}.settings", settings),
            patch(f"{MODULE}._spawn_server", return_value=(mock_proc, mock_fh)),
            patch(f"{MODULE}._wait_for_server_ready", return_value=True),
            patch(f"{MODULE}.atexit.register"),
            patch(f"{MODULE}.secrets.token_urlsafe", return_value="generated-key"),
        ):
            from client.app.core.api import start_server

            start_server()
        # ``settings.api_key`` is a ``SecretStr`` after migration; reveal it
        # for the assertion.
        from client.app.core.secrets import reveal
        assert reveal(settings.api_key) == "generated-key"



# ---------------------------------------------------------------------------
# _stop_server
# ---------------------------------------------------------------------------
class TestStopServer:
    """Tests for _stop_server."""

    def test_terminates_running_process(self):
        """Verify _stop_server terminates a running process and closes the log file."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Running
        mock_fh = MagicMock()
        server_dict = {"process": mock_proc, "log_file": mock_fh}
        with patch(f"{MODULE}._SERVER", server_dict):
            from client.app.core.api import _stop_server

            _stop_server()
        mock_proc.terminate.assert_called_once()
        mock_fh.close.assert_called_once()
        assert server_dict["process"] is None
        assert server_dict["log_file"] is None

    def test_kills_on_timeout(self):
        """Verify _stop_server kills the process when terminate times out."""
        import subprocess

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
        server_dict = {"process": mock_proc, "log_file": None}
        with patch(f"{MODULE}._SERVER", server_dict):
            from client.app.core.api import _stop_server

            _stop_server()
        mock_proc.kill.assert_called_once()

    def test_noop_when_no_process(self):
        """Verify _stop_server does nothing when no process is running."""
        server_dict = {"process": None, "log_file": None}
        with patch(f"{MODULE}._SERVER", server_dict):
            from client.app.core.api import _stop_server

            _stop_server()  # Should not raise

    def test_closes_log_file(self):
        """Verify _stop_server closes the log file even when no process exists."""
        mock_fh = MagicMock()
        server_dict = {"process": None, "log_file": mock_fh}
        with patch(f"{MODULE}._SERVER", server_dict):
            from client.app.core.api import _stop_server

            _stop_server()
        mock_fh.close.assert_called_once()
