"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for logging_redaction.py.
"""

import builtins
import logging
import sys

import pytest

from logging_redaction import (
    _STATIC_SENSITIVE_KEYS,
    REDACTED,
    RedactingFilter,
    _sensitive_keys,
)


def _server_schemas_importable() -> bool:
    try:
        from server.app.database.schemas import DatabaseSensitive  # noqa: F401
        from server.app.models.defaults import ENV_OVERRIDES  # noqa: F401
        from server.app.models.schemas import ModelSensitive  # noqa: F401
        from server.app.oci.schemas import OciSensitive  # noqa: F401
    except ImportError:
        return False
    return True


_SERVER_SCHEMAS_AVAILABLE = _server_schemas_importable()
_requires_server_schemas = pytest.mark.skipif(
    not _SERVER_SCHEMAS_AVAILABLE,
    reason="server schemas not importable (client-only test env)",
)


def _make_record(msg: str, args: tuple = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=args,
        exc_info=None,
    )


@pytest.fixture
def filt() -> RedactingFilter:
    return RedactingFilter()


class TestKeyValueRedaction:
    """Verify the KV pattern handles each documented input shape."""

    def test_bare_kv(self, filt):
        record = _make_record("password=secret123")
        filt.filter(record)
        assert record.getMessage() == f"password={REDACTED}"

    def test_bare_kv_single_quoted_value(self, filt):
        record = _make_record("password='secret 123'")
        filt.filter(record)
        assert record.getMessage() == f"password={REDACTED}"

    def test_bare_kv_double_quoted_value(self, filt):
        record = _make_record('password="secret 123"')
        filt.filter(record)
        assert record.getMessage() == f"password={REDACTED}"

    def test_json_style_quoted_key(self, filt):
        record = _make_record('{"api_key": "sk-abc"}')
        filt.filter(record)
        # Quote shape preserved on the key.
        assert "sk-abc" not in record.getMessage()
        assert f'"api_key": {REDACTED}' in record.getMessage()

    def test_python_repr_style_quoted_key(self, filt):
        record = _make_record("{'api_key': 'sk-abc'}")
        filt.filter(record)
        assert "sk-abc" not in record.getMessage()
        assert f"'api_key': {REDACTED}" in record.getMessage()

    def test_yaml_style_colon(self, filt):
        record = _make_record("wallet_password: shh")
        filt.filter(record)
        assert "shh" not in record.getMessage()
        assert f"wallet_password: {REDACTED}" in record.getMessage()

    def test_env_var_alias_assignment(self, filt):
        record = _make_record("AIO_DB_PASSWORD=hunter2")
        filt.filter(record)
        assert "hunter2" not in record.getMessage()

    def test_env_var_alias_quoted(self, filt):
        record = _make_record("AIO_API_KEY='sk-abc'")
        filt.filter(record)
        assert "sk-abc" not in record.getMessage()

    def test_args_redacted_after_format(self, filt):
        record = _make_record("user=%s pwd=%s", ("alice", "shh"))
        filt.filter(record)
        # ``pwd`` is not in the keyset, so the value is not redacted.  This
        # test pins the documented behavior: the filter operates on the
        # formatted message and only matches keys that are present in the
        # keyset.  ``alice`` should remain (user is not sensitive).
        assert "alice" in record.getMessage()

    def test_unquoted_multiline_pem_block_redacted(self, filt):
        """PEM-formatted blocks are redacted as a whole, including body and
        END marker, not just the leading BEGIN token.
        """
        body = (
            "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDZ4exampleBODY"
            "ABCDE+FGHIJKLMNOPQRSTUVWXYZabcdef0123456789exampleBODYabcdef"
        )
        record = _make_record(
            "OCI_CLI_KEY_CONTENT=-----BEGIN RSA PRIVATE KEY-----\n"
            f"{body}\n"
            "-----END RSA PRIVATE KEY-----"
        )
        filt.filter(record)
        scrubbed = record.getMessage()
        assert body not in scrubbed
        assert "PRIVATE KEY-----" not in scrubbed
        assert "BEGIN RSA" not in scrubbed

    def test_unquoted_value_with_internal_spaces_redacted(self, filt):
        """An unquoted credential value containing spaces is redacted in
        full, not truncated at the first whitespace.
        """
        record = _make_record("password=my secret pass phrase here")
        filt.filter(record)
        scrubbed = record.getMessage()
        assert "secret" not in scrubbed
        assert "phrase" not in scrubbed

    @pytest.mark.parametrize(
        "env_name",
        ["OPENAI_API_KEY", "COHERE_API_KEY", "PPLX_API_KEY"],
    )
    def test_provider_api_key_env_assignment_redacted(self, filt, env_name):
        """Provider-specific API key env vars are recognised by the filter."""
        record = _make_record(f"{env_name}=sk-redacted-test-value-1234")
        filt.filter(record)
        assert "sk-redacted-test-value-1234" not in record.getMessage()

    @pytest.mark.parametrize(
        "env_name",
        ["AIO_OPENAI_API_KEY", "AIO_COHERE_API_KEY", "AIO_PPLX_API_KEY"],
    )
    def test_aio_prefixed_provider_api_key_env_assignment_redacted(self, filt, env_name):
        """AIO_-prefixed provider API key env vars are also recognised."""
        record = _make_record(f"{env_name}=sk-aio-redacted-test")
        filt.filter(record)
        assert "sk-aio-redacted-test" not in record.getMessage()

    def test_http_auth_header_value_redacted(self, filt):
        """The X-API-Key auth header value is redacted in colon-style and
        Python-repr-style header dumps.
        """
        for record in (
            _make_record("X-API-Key: tok-redacted-test-abc123"),
            _make_record("{'X-API-Key': 'tok-redacted-test-xyz789'}"),
        ):
            filt.filter(record)
            assert "tok-redacted-test" not in record.getMessage()

    def test_double_quoted_value_with_escaped_quote_redacted(self, filt):
        """An escaped double-quote inside a JSON-style value does not
        truncate the match; the full content is redacted.
        """
        # Runtime input: {"api_key": "abc\"def"}
        record = _make_record('{"api_key": "abc\\"def"}')
        filt.filter(record)
        scrubbed = record.getMessage()
        assert "abc" not in scrubbed
        assert "def" not in scrubbed

    def test_single_quoted_value_with_escaped_quote_redacted(self, filt):
        """An escaped single-quote inside a Python-repr-style value does
        not truncate the match.
        """
        # Runtime input: {'api_key': 'abc\'def'}
        record = _make_record("{'api_key': 'abc\\'def'}")
        filt.filter(record)
        scrubbed = record.getMessage()
        assert "abc" not in scrubbed
        assert "def" not in scrubbed


class TestNonRedactionCases:
    """Inputs that must NOT be redacted."""

    def test_password_substring(self, filt):
        # "password resets" contains the word password but not as a key=value.
        record = _make_record("processing 5 password resets today")
        filt.filter(record)
        assert record.getMessage() == "processing 5 password resets today"

    def test_key_file_path_unchanged(self, filt):
        # ``key_file`` is not in the keyset; path values must be preserved.
        record = _make_record("key_file=/path/to/file")
        filt.filter(record)
        assert "/path/to/file" in record.getMessage()

    def test_fingerprint_unchanged(self, filt):
        # Public identifier — explicitly excluded from the keyset.
        record = _make_record("fingerprint=aa:bb:cc:dd")
        filt.filter(record)
        assert "aa:bb:cc:dd" in record.getMessage()

    def test_word_boundary_prevents_partial_match(self, filt):
        # ``mypassword=...`` should NOT be redacted because ``password`` is
        # not at a word boundary.
        record = _make_record("mypassword=visible")
        filt.filter(record)
        assert "visible" in record.getMessage()


class TestDsnRedaction:
    """Verify embedded credentials in connection strings are scrubbed."""

    def test_oracle_dsn(self, filt):
        record = _make_record("oracle://scott:tiger@db.host:1521/svc")
        filt.filter(record)
        assert "tiger" not in record.getMessage()
        assert f"oracle://scott:{REDACTED}@db.host:1521/svc" in record.getMessage()

    def test_postgres_dsn(self, filt):
        record = _make_record("connecting to postgresql://app:s3cret@pg.host/db")
        filt.filter(record)
        assert "s3cret" not in record.getMessage()


class TestFilterAttributes:
    """Filter exposes ``key_count`` / ``key_source`` for caller-side observability."""

    @_requires_server_schemas
    def test_schemas_path_default(self, filt):
        # Server schemas are importable in this test environment.
        assert filt.key_source == "schemas"
        assert filt.key_count >= len(_STATIC_SENSITIVE_KEYS)

    def test_static_fallback(self, monkeypatch):
        # Schema modules may already be cached in ``sys.modules`` from earlier
        # tests in the same session, so monkeypatching just the import won't
        # trigger ImportError.  Pop the cached modules first, then patch
        # ``builtins.__import__`` to fail on the relevant prefixes.
        for mod in (
            "server.app.database.schemas",
            "server.app.models.schemas",
            "server.app.oci.schemas",
        ):
            monkeypatch.delitem(sys.modules, mod, raising=False)
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name.startswith("server.app."):
                raise ImportError(f"simulated: {name}")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        f = RedactingFilter()
        assert f.key_source == "static"
        assert f.key_count == len(_STATIC_SENSITIVE_KEYS)


class TestKeysetParity:
    """Schema-derived keyset must match the static fallback set.

    Keeps the import-backed and fallback keysets aligned for environments
    where the server schemas are not on the path.
    """

    @_requires_server_schemas
    def test_schema_and_static_match(self):
        keys, source = _sensitive_keys()
        assert source == "schemas"
        assert keys == _STATIC_SENSITIVE_KEYS


class TestFilterAlwaysReturnsTrue:
    """The filter must never drop a record — it only mutates content."""

    def test_unmatched_record(self, filt):
        record = _make_record("nothing sensitive here")
        assert filt.filter(record) is True

    def test_matched_record(self, filt):
        record = _make_record("password=foo")
        assert filt.filter(record) is True

    def test_unformattable_message(self, filt):
        # ``%`` formatting failure must not drop the record.
        record = _make_record("user=%s pwd=%s", ("only-one-arg",))
        assert filt.filter(record) is True


class TestStartupObservability:
    """``configure_logging`` emits a debug line with the filter's provenance.

    ``dictConfig`` replaces the root logger's handlers, so pytest's ``caplog``
    propagation handler is detached.  Capture stderr (where the configured
    StreamHandler emits) instead.
    """

    def test_startup_log_line(self, capsys):
        import logging_config

        logging_config.configure_logging(log_level="DEBUG")
        captured = capsys.readouterr()
        assert "redaction filter initialized" in captured.err
        assert ("source=schemas" in captured.err) or ("source=static" in captured.err)
