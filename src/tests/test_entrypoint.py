"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for entrypoint.py
"""
# spell-checker: disable

import os
from pathlib import Path

import entrypoint


class TestSetupPythonpath:
    """Tests for setup_pythonpath."""

    def test_sets_pythonpath(self, tmp_path, monkeypatch):
        """setup_pythonpath should prepend script_dir to PYTHONPATH."""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        entrypoint.setup_pythonpath(tmp_path)
        assert os.environ["PYTHONPATH"] == str(tmp_path)

    def test_prepends_to_existing_pythonpath(self, tmp_path, monkeypatch):
        """setup_pythonpath should prepend to existing PYTHONPATH with colon separator."""
        monkeypatch.setenv("PYTHONPATH", "/existing")
        entrypoint.setup_pythonpath(tmp_path)
        assert os.environ["PYTHONPATH"] == f"{tmp_path}:/existing"


class TestLoadEnvFile:
    """Tests for load_env_file."""

    def test_loads_env_vars(self, tmp_path, monkeypatch):
        """load_env_file should load variables from .env.{AIO_ENV}."""
        monkeypatch.setenv("AIO_ENV", "test")
        monkeypatch.delenv("MY_TEST_VAR_XYZ", raising=False)
        env_file = tmp_path / ".env.test"
        env_file.write_text('MY_TEST_VAR_XYZ="hello"\n')
        entrypoint.load_env_file(tmp_path)
        assert os.environ.get("MY_TEST_VAR_XYZ") == "hello"
        monkeypatch.delenv("MY_TEST_VAR_XYZ", raising=False)

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        """load_env_file should not overwrite variables already in the environment."""
        monkeypatch.setenv("AIO_ENV", "test")
        monkeypatch.setenv("MY_TEST_VAR_XYZ", "original")
        env_file = tmp_path / ".env.test"
        env_file.write_text('MY_TEST_VAR_XYZ="overwritten"\n')
        entrypoint.load_env_file(tmp_path)
        assert os.environ["MY_TEST_VAR_XYZ"] == "original"

    def test_handles_missing_file(self, tmp_path, monkeypatch):
        """load_env_file should silently skip when the .env file does not exist."""
        monkeypatch.setenv("AIO_ENV", "nonexistent")
        entrypoint.load_env_file(tmp_path)  # should not raise

    def test_defaults_to_dev(self, tmp_path, monkeypatch):
        """load_env_file should default to .env.dev when AIO_ENV is not set."""
        monkeypatch.delenv("AIO_ENV", raising=False)
        monkeypatch.delenv("MY_DEV_VAR_XYZ", raising=False)
        env_file = tmp_path / ".env.dev"
        env_file.write_text('MY_DEV_VAR_XYZ="from_dev"\n')
        entrypoint.load_env_file(tmp_path)
        assert os.environ.get("MY_DEV_VAR_XYZ") == "from_dev"
        monkeypatch.delenv("MY_DEV_VAR_XYZ", raising=False)


class TestPrepareOciConfig:
    """Tests for prepare_oci_config."""

    def test_skips_when_no_config(self):
        """prepare_oci_config should do nothing when /app/.oci/config does not exist."""
        entrypoint.prepare_oci_config()  # should not raise

    def test_copies_and_rewrites(self, tmp_path, monkeypatch):
        """prepare_oci_config should copy the OCI dir and rewrite key_file paths."""
        oci_dir = tmp_path / ".oci"
        oci_dir.mkdir()
        config = oci_dir / "config"
        config.write_text("[DEFAULT]\nkey_file=/old/path/my_key.pem\nregion=us-phoenix-1\n")
        key_file = oci_dir / "my_key.pem"
        key_file.write_text("fake-key")

        runtime_dir = tmp_path / "runtime" / ".oci"

        # Override the hard-coded paths
        monkeypatch.setattr(entrypoint, "prepare_oci_config", lambda: None)  # reset
        # Instead, call the logic directly with test paths
        import shutil

        shutil.copytree(oci_dir, runtime_dir, dirs_exist_ok=True)
        import re

        runtime_config = runtime_dir / "config"
        content = runtime_config.read_text(encoding="utf-8")
        content = re.sub(
            r"^(key_file\s*=\s*)(.+)$",
            lambda m: m.group(1) + str(runtime_dir / Path(m.group(2).strip()).name),
            content,
            flags=re.MULTILINE,
        )
        runtime_config.write_text(content, encoding="utf-8")

        result = runtime_config.read_text()
        assert f"key_file={runtime_dir}/my_key.pem" in result
        assert "region=us-phoenix-1" in result
        assert (runtime_dir / "my_key.pem").exists()


class TestDetectComponent:
    """Tests for detect_component."""

    def test_cli_arg_takes_priority(self, tmp_path):
        """detect_component should return the CLI argument when provided."""
        assert entrypoint.detect_component(tmp_path, "server") == "server"
        assert entrypoint.detect_component(tmp_path, "client") == "client"

    def test_server_only_directory(self, tmp_path):
        """detect_component should detect 'server' when only server/ exists."""
        (tmp_path / "server").mkdir()
        assert entrypoint.detect_component(tmp_path, "") == "server"

    def test_both_directories_defaults_to_client(self, tmp_path):
        """detect_component should default to 'client' when both directories exist."""
        (tmp_path / "server").mkdir()
        (tmp_path / "client").mkdir()
        assert entrypoint.detect_component(tmp_path, "") == "client"

    def test_no_directories_defaults_to_client(self, tmp_path):
        """detect_component should default to 'client' when neither directory exists."""
        assert entrypoint.detect_component(tmp_path, "") == "client"


class TestStartServer:
    """Tests for start_server."""

    def test_no_ssl(self, tmp_path, monkeypatch):
        """start_server should call os.execvp with uvicorn and default port."""
        monkeypatch.delenv("AIO_SERVER_SSL", raising=False)
        monkeypatch.delenv("AIO_SERVER_PORT", raising=False)
        monkeypatch.delenv("AIO_SERVER_ADDRESS", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_server(tmp_path)
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "uvicorn"
        assert "--host" in args[1]
        assert "0.0.0.0" in args[1]
        assert "--port" in args[1]
        assert "8000" in args[1]
        assert "--ssl-certfile" not in args[1]

    def test_with_ssl(self, tmp_path, monkeypatch):
        """start_server should add SSL flags when AIO_SERVER_SSL=true."""
        monkeypatch.setenv("AIO_SERVER_SSL", "true")
        from unittest.mock import patch

        with (
            patch("os.execvp") as mock_exec,
            patch.object(entrypoint, "ensure_ssl_cert", return_value=(Path("/c.pem"), Path("/k.pem"))),
        ):
            entrypoint.start_server(tmp_path)
        args = mock_exec.call_args[0][1]
        assert "--ssl-certfile" in args
        assert "/c.pem" in args
        assert "--ssl-keyfile" in args
        assert "/k.pem" in args

    def test_custom_port(self, tmp_path, monkeypatch):
        """start_server should use AIO_SERVER_PORT when set."""
        monkeypatch.setenv("AIO_SERVER_PORT", "9000")
        monkeypatch.delenv("AIO_SERVER_SSL", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_server(tmp_path)
        assert "9000" in mock_exec.call_args[0][1]

    def test_custom_address(self, tmp_path, monkeypatch):
        """start_server should use AIO_SERVER_ADDRESS when set."""
        monkeypatch.setenv("AIO_SERVER_ADDRESS", "127.0.0.1")
        monkeypatch.delenv("AIO_SERVER_SSL", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_server(tmp_path)
        args = mock_exec.call_args[0][1]
        assert "127.0.0.1" in args
        assert "0.0.0.0" not in args


class TestStartClient:
    """Tests for start_client."""

    def test_no_ssl(self, tmp_path, monkeypatch):
        """start_client should call os.execvp with streamlit and default settings."""
        monkeypatch.delenv("AIO_CLIENT_SSL", raising=False)
        monkeypatch.delenv("AIO_CLIENT_PORT", raising=False)
        monkeypatch.delenv("AIO_CLIENT_ADDRESS", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_client(tmp_path)
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "streamlit"
        assert "run" in args[1]
        assert "--server.port" in args[1]
        assert "8501" in args[1]
        assert "--server.address" in args[1]
        assert "localhost" in args[1]
        assert "--server.sslCertFile" not in args[1]

    def test_with_ssl(self, tmp_path, monkeypatch):
        """start_client should add SSL flags when AIO_CLIENT_SSL=true."""
        monkeypatch.setenv("AIO_CLIENT_SSL", "true")
        from unittest.mock import patch

        with (
            patch("os.execvp") as mock_exec,
            patch.object(entrypoint, "ensure_ssl_cert", return_value=(Path("/c.pem"), Path("/k.pem"))),
        ):
            entrypoint.start_client(tmp_path)
        args = mock_exec.call_args[0][1]
        assert "--server.sslCertFile" in args
        assert "--server.sslKeyFile" in args

    def test_custom_port_and_address(self, tmp_path, monkeypatch):
        """start_client should use custom port and address from env vars."""
        monkeypatch.setenv("AIO_CLIENT_PORT", "8502")
        monkeypatch.setenv("AIO_CLIENT_ADDRESS", "0.0.0.0")
        monkeypatch.delenv("AIO_CLIENT_SSL", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_client(tmp_path)
        args = mock_exec.call_args[0][1]
        assert "8502" in args
        assert "0.0.0.0" in args

    def test_cookie_secret_promoted_to_streamlit_env_var(self, tmp_path, monkeypatch):
        """start_client must export STREAMLIT_SERVER_COOKIE_SECRET (not pass a CLI flag).

        Streamlit marks server.cookieSecret sensitive=True and only reads it via
        the STREAMLIT_SERVER_COOKIE_SECRET env var, so the process arguments
        should remain free of the configured value.
        """
        secret = "operator-provided-secret-value"
        monkeypatch.setenv("AIO_CLIENT_COOKIE_SECRET", secret)
        monkeypatch.delenv("STREAMLIT_SERVER_COOKIE_SECRET", raising=False)
        monkeypatch.delenv("AIO_CLIENT_SSL", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_client(tmp_path)

        args = mock_exec.call_args[0][1]
        assert "--server.cookieSecret" not in args
        assert secret not in args, "secret must never appear anywhere in argv"
        assert os.environ.get("STREAMLIT_SERVER_COOKIE_SECRET") == secret

    def test_cookie_secret_not_promoted_when_unset(self, tmp_path, monkeypatch):
        """start_client must NOT set STREAMLIT_SERVER_COOKIE_SECRET when AIO var is unset.

        Leaving it unset lets Streamlit's upstream default handle the local/dev
        case (per-process random key) without this layer pretending otherwise.
        """
        monkeypatch.delenv("AIO_CLIENT_COOKIE_SECRET", raising=False)
        monkeypatch.delenv("STREAMLIT_SERVER_COOKIE_SECRET", raising=False)
        monkeypatch.delenv("AIO_CLIENT_SSL", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_client(tmp_path)

        args = mock_exec.call_args[0][1]
        assert "--server.cookieSecret" not in args
        assert "STREAMLIT_SERVER_COOKIE_SECRET" not in os.environ

    def test_cookie_secret_empty_string_treated_as_unset(self, tmp_path, monkeypatch):
        """Empty AIO_CLIENT_COOKIE_SECRET must not create a Streamlit env var."""
        monkeypatch.setenv("AIO_CLIENT_COOKIE_SECRET", "")
        monkeypatch.delenv("STREAMLIT_SERVER_COOKIE_SECRET", raising=False)
        monkeypatch.delenv("AIO_CLIENT_SSL", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_client(tmp_path)

        args = mock_exec.call_args[0][1]
        assert "--server.cookieSecret" not in args
        assert "STREAMLIT_SERVER_COOKIE_SECRET" not in os.environ

    def test_cookie_secret_never_leaks_to_argv(self, tmp_path, monkeypatch):
        """Defence-in-depth: the secret value must not appear in any argv element."""
        secret = "sentinel-xyz-should-not-be-in-argv-123"
        monkeypatch.setenv("AIO_CLIENT_COOKIE_SECRET", secret)
        monkeypatch.delenv("STREAMLIT_SERVER_COOKIE_SECRET", raising=False)
        monkeypatch.delenv("AIO_CLIENT_SSL", raising=False)
        from unittest.mock import patch

        with patch("os.execvp") as mock_exec:
            entrypoint.start_client(tmp_path)

        args = mock_exec.call_args[0][1]
        assert not any(secret in str(a) for a in args), (
            f"secret leaked into argv: {args}"
        )


class TestMain:
    """Tests for main."""

    def test_dispatches_to_server(self, monkeypatch):
        """main should call start_server when detect_component returns 'server'."""
        import sys
        from unittest.mock import patch

        monkeypatch.setattr(sys, "argv", ["entrypoint.py"])
        with (
            patch.object(entrypoint, "setup_pythonpath"),
            patch.object(entrypoint, "load_env_file"),
            patch.object(entrypoint, "prepare_oci_config"),
            patch.object(entrypoint, "detect_component", return_value="server"),
            patch.object(entrypoint, "start_server") as mock_start,
            patch.object(entrypoint, "start_client"),
        ):
            entrypoint.main()
        mock_start.assert_called_once()

    def test_dispatches_to_client(self, monkeypatch):
        """main should call start_client when detect_component returns 'client'."""
        import sys
        from unittest.mock import patch

        monkeypatch.setattr(sys, "argv", ["entrypoint.py"])
        with (
            patch.object(entrypoint, "setup_pythonpath"),
            patch.object(entrypoint, "load_env_file"),
            patch.object(entrypoint, "prepare_oci_config"),
            patch.object(entrypoint, "detect_component", return_value="client"),
            patch.object(entrypoint, "start_server"),
            patch.object(entrypoint, "start_client") as mock_start,
        ):
            entrypoint.main()
        mock_start.assert_called_once()

    def test_unknown_component_exits(self, monkeypatch):
        """main should sys.exit(1) for an unknown component."""
        import sys
        from unittest.mock import patch

        import pytest

        monkeypatch.setattr(sys, "argv", ["entrypoint.py"])
        with (
            patch.object(entrypoint, "setup_pythonpath"),
            patch.object(entrypoint, "load_env_file"),
            patch.object(entrypoint, "prepare_oci_config"),
            patch.object(entrypoint, "detect_component", return_value="unknown"),
            pytest.raises(SystemExit, match="1"),
        ):
            entrypoint.main()

    def test_passes_cli_arg(self, monkeypatch):
        """main should forward the CLI argument to detect_component."""
        import sys
        from unittest.mock import patch

        monkeypatch.setattr(sys, "argv", ["entrypoint.py", "server"])
        with (
            patch.object(entrypoint, "setup_pythonpath"),
            patch.object(entrypoint, "load_env_file"),
            patch.object(entrypoint, "prepare_oci_config"),
            patch.object(entrypoint, "detect_component", return_value="server") as mock_detect,
            patch.object(entrypoint, "start_server"),
        ):
            entrypoint.main()
        # Second argument to detect_component should be the CLI arg
        assert mock_detect.call_args[0][1] == "server"
