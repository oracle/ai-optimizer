"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.database.schemas — Pydantic model defaults and validation.
"""
# spell-checker: disable

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from server.app.core.secrets import REVEAL_KEY, reveal
from server.app.database.schemas import (
    DatabaseConfig,
    DatabaseSensitive,
    DatabaseUpdate,
)
from server.app.embed.schemas import VectorStoreConfig

pytestmark = [pytest.mark.unit]

_FORBIDDEN = ["\n", "\r", "\x00"]
_FORBIDDEN_IDS = ["newline", "carriage_return", "nul"]


# ---------------------------------------------------------------------------
# VectorStoreConfig
# ---------------------------------------------------------------------------


class TestVectorStoreConfig:
    """Test VectorStoreConfig defaults."""

    def test_vector_store_readonly_schema(self):
        """vector_store field has readOnly in JSON schema."""
        schema = VectorStoreConfig.model_json_schema()
        vs_prop = schema["properties"]["vector_store"]
        assert vs_prop.get("readOnly") is True


# ---------------------------------------------------------------------------
# DatabaseConfig
# ---------------------------------------------------------------------------


class TestDatabaseConfig:
    """Test DatabaseConfig defaults and serialization."""

    def test_pool_excluded_from_serialization(self):
        """pool field is excluded from model_dump."""
        dc = DatabaseConfig(alias="TEST")
        dumped = dc.model_dump()
        assert "pool" not in dumped

    def test_inherits_sensitive_fields(self):
        """DatabaseConfig inherits password and wallet_password from DatabaseSensitive."""
        dc = DatabaseConfig(
            alias="TEST",
            password=SecretStr("secret"),
            wallet_password=SecretStr("wallet_secret"),
        )
        assert reveal(dc.password) == "secret"
        assert reveal(dc.wallet_password) == "wallet_secret"


# ---------------------------------------------------------------------------
# Control-character rejection for SQLcl-bound fields
# ---------------------------------------------------------------------------


class TestControlCharRejection:
    """Credential/identifier fields must reject newline, CR, and NUL.

    SQLcl-bound values are validated at the Pydantic boundary so
    configuration.json, environment variables, and HTTP endpoints apply
    the same input contract.
    """

    # Fields for which newline/CR/NUL are all rejected.
    # `dsn` is intentionally excluded — Oracle connect descriptors are
    # legitimately multi-line (see docs/content/help/troubleshooting/_index.md).
    _DB_CONFIG_FIELDS = [
        "alias",
        "username",
        "password",
        "wallet_password",
        "wallet_location",
        "config_dir",
    ]
    _DB_UPDATE_FIELDS = [
        "username",
        "password",
        "wallet_password",
        "wallet_location",
        "config_dir",
    ]

    @pytest.mark.parametrize("field", _DB_CONFIG_FIELDS)
    @pytest.mark.parametrize("char", _FORBIDDEN, ids=_FORBIDDEN_IDS)
    def test_database_config_rejects_control_char(self, field: str, char: str):
        """DatabaseConfig refuses control chars in every string field."""
        kwargs: dict[str, Any] = {"alias": "TEST"}
        kwargs[field] = f"a{char}b"
        with pytest.raises(ValidationError) as excinfo:
            DatabaseConfig(**kwargs)
        assert field in str(excinfo.value)

    @pytest.mark.parametrize("field", _DB_UPDATE_FIELDS)
    @pytest.mark.parametrize("char", _FORBIDDEN, ids=_FORBIDDEN_IDS)
    def test_database_update_rejects_control_char(self, field: str, char: str):
        """DatabaseUpdate refuses control chars in every string field."""
        kwargs: dict[str, Any] = {field: f"a{char}b"}
        with pytest.raises(ValidationError) as excinfo:
            DatabaseUpdate(**kwargs)
        assert field in str(excinfo.value)

    @pytest.mark.parametrize("char", _FORBIDDEN, ids=_FORBIDDEN_IDS)
    def test_database_sensitive_rejects_control_char_in_password(self, char: str):
        """DatabaseSensitive (base class) refuses control chars in password."""
        with pytest.raises(ValidationError):
            DatabaseSensitive(password=SecretStr(f"a{char}b"))

    @pytest.mark.parametrize("bad_value", [123, 12.5, True, ["x"], {"k": "v"}])
    def test_database_config_non_string_password_yields_validation_error(self, bad_value):
        """Non-string ``password`` values raise ValidationError."""
        with pytest.raises(ValidationError):
            DatabaseConfig(alias="TEST", password=bad_value)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_value", [123, 12.5, True, ["x"], {"k": "v"}])
    def test_database_update_non_string_password_yields_validation_error(self, bad_value):
        """The same contract applies to the update schema."""
        with pytest.raises(ValidationError):
            DatabaseUpdate(password=bad_value)  # type: ignore[arg-type]

    def test_password_with_embedded_newline_is_rejected(self):
        """A password containing an embedded newline must be rejected at the schema layer."""
        with pytest.raises(ValidationError) as excinfo:
            DatabaseConfig(
                alias="TEST",
                username="scott",
                password=SecretStr('x"\ny\n#'),
                dsn="db",
            )
        assert "password" in str(excinfo.value)

    @pytest.mark.parametrize("char", ["\n", "\r"], ids=["newline", "carriage_return"])
    def test_dsn_accepts_multiline_descriptor_verbatim(self, char: str):
        """Multi-line descriptors are accepted and preserved as-given.

        Internal whitespace inside a descriptor is significant to some
        consumers (e.g. SSL_SERVER_CERT_DN values include spaces that Oracle
        matches exactly), so the schema must NOT rewrite descriptor
        internals. Downstream consumers cope with the whitespace themselves:
        the retry-strip regex tolerates it, and the SQLcl sink flattens
        newlines to spaces at the very last step.
        """
        value = f"(DESCRIPTION = {char}(ADDRESS = (PROTOCOL = tcps)))"
        dc = DatabaseConfig(alias="TEST", dsn=value)
        assert dc.dsn == value

        u = DatabaseUpdate(dsn=value)
        assert u.dsn == value

    def test_dsn_multiline_description_from_docs_is_preserved(self):
        """The exact multi-line DSN shape from the troubleshooting doc loads
        unchanged. Spaces and newlines are preserved verbatim."""
        multiline_dsn = (
            "(DESCRIPTION = \n"
            "  (ADDRESS = \n"
            "    (PROTOCOL = tcps)(HOST = adb_host)(PORT = 1522)\n"
            "    (HTTPS_PROXY = proxy_host)(HTTPS_PROXY_PORT = 80)\n"
            "  )\n"
            "  (CONNECT_DATA = (SERVICE_NAME = svc))\n"
            ")"
        )
        dc = DatabaseConfig(alias="TEST", dsn=multiline_dsn)
        assert dc.dsn == multiline_dsn

    @pytest.mark.parametrize(
        "dsn",
        [
            # Newline inside a quoted DN value
            '(DESCRIPTION=(SECURITY=(SSL_SERVER_CERT_DN="CN=a,\nOU=b")))',
            # CR inside a quoted value
            '(DESCRIPTION=(SECURITY=(SSL_SERVER_CERT_DN="CN=a,\rOU=b")))',
            # Line break inside a quoted wallet path
            '(DESCRIPTION=(SECURITY=(MY_WALLET_DIRECTORY="/opt/a\nb")))',
        ],
        ids=["dn_with_lf", "dn_with_cr", "wallet_path_with_lf"],
    )
    def test_dsn_rejects_linebreak_inside_quoted_descriptor_value(self, dsn: str):
        """A line break inside a quoted descriptor value is ambiguous: oracledb
        keeps it as part of the value; SQLcl would break on its stdin parser.
        Fail fast at validation rather than diverge silently between paths.
        """
        with pytest.raises(ValidationError) as excinfo:
            DatabaseConfig(alias="TEST", dsn=dsn)
        msg = str(excinfo.value)
        assert "dsn" in msg
        assert "inside a quoted" in msg

        with pytest.raises(ValidationError):
            DatabaseUpdate(dsn=dsn)

    @pytest.mark.parametrize(
        "dsn",
        [
            "(DESCRIPTION=(ADDRESS=(HOST=adb\nhost)))",  # \n inside HOST value
            "(DESCRIPTION=(ADDRESS=(HOST=adb\rhost)))",  # \r inside HOST value
            "(DESCRIPTION=(SECURITY=(MY_WALLET_DIRECTORY=/opt/my\nwallet)))",
            "(DESCRIPTION=(ADDRESS=(PORT=15\n21)))",  # line break splitting a numeric value
            # Comma is value content in an X.500 DN, not a descriptor
            # delimiter — a line break after the comma still sits inside
            # the value. oracledb would keep the newline, SQLcl would
            # rewrite it to a space → different DNs on the two paths.
            "(DESCRIPTION=(SECURITY=(SSL_SERVER_CERT_DN=CN=adb,\nOU=Oracle)))",
            "(DESCRIPTION=(SECURITY=(SSL_SERVER_CERT_DN=CN=adb,\n OU=Oracle)))",
        ],
        ids=[
            "host_with_lf",
            "host_with_cr",
            "wallet_path_with_lf",
            "port_split",
            "unquoted_dn_lf_after_comma",
            "unquoted_dn_lf_and_space_after_comma",
        ],
    )
    def test_dsn_rejects_linebreak_inside_unquoted_descriptor_value(self, dsn: str):
        """Line breaks splitting an unquoted value make oracledb and SQLcl
        see different tokens after sink-level flattening. Reject at schema
        so the two paths always agree.
        """
        with pytest.raises(ValidationError) as excinfo:
            DatabaseConfig(alias="TEST", dsn=dsn)
        msg = str(excinfo.value)
        assert "dsn" in msg
        assert "unquoted" in msg

        with pytest.raises(ValidationError):
            DatabaseUpdate(dsn=dsn)

    @pytest.mark.parametrize(
        "dsn",
        [
            # Line break between CONNECT_DATA close and next sibling — structural.
            "(DESCRIPTION=(ADDRESS=(HOST=h))\n(CONNECT_DATA=(SERVICE_NAME=svc)))",
            # Line break right after `=` but before the nested `(`.
            "(DESCRIPTION=\n(ADDRESS=(HOST=h)))",
            # Line break right after `)` — end of a value token.
            "(DESCRIPTION=(HOST=h)\n)",
        ],
        ids=[
            "between_sibling_parens",
            "after_equals_before_paren",
            "after_closing_paren",
        ],
    )
    def test_dsn_allows_structural_linebreaks(self, dsn: str):
        """Line breaks at token boundaries are legal — they are adjacent to
        structural delimiters and do not split a value."""
        dc = DatabaseConfig(alias="TEST", dsn=dsn)
        assert dc.dsn == dsn

    def test_dsn_preserves_spaces_inside_descriptor_values(self):
        """Meaningful spaces inside descriptor values (DNs, wallet paths)
        must survive schema validation unchanged — aggressive whitespace
        collapse would corrupt them and break Oracle's exact-match
        comparison for certificate DNs."""
        # An ADB-style DN: Oracle compares these character-for-character.
        dsn = (
            '(DESCRIPTION=(ADDRESS=(PROTOCOL=tcps)(HOST=adb.example.com)(PORT=1522))'
            '(CONNECT_DATA=(SERVICE_NAME=svc))'
            '(SECURITY=(SSL_SERVER_CERT_DN='
            '"CN=adb.example.com, OU=Oracle BMCS US, O=Oracle Corporation, L=Redwood City, ST=California, C=US"'
            ")))"
        )
        dc = DatabaseConfig(alias="TEST", dsn=dsn)
        assert dc.dsn == dsn
        # Specifically: the spaces inside the quoted DN value are untouched.
        assert "CN=adb.example.com, OU=Oracle BMCS US, O=Oracle Corporation" in dc.dsn

        # Wallet directory with spaces in the path.
        dsn_wallet = (
            "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcps)(HOST=h)(PORT=1522))"
            "(CONNECT_DATA=(SERVICE_NAME=svc))"
            "(SECURITY=(MY_WALLET_DIRECTORY=/opt/oracle/my wallet dir)))"
        )
        dc2 = DatabaseConfig(alias="TEST", dsn=dsn_wallet)
        assert dc2.dsn == dsn_wallet
        assert "/opt/oracle/my wallet dir" in dc2.dsn

    def test_dsn_still_rejects_nul(self):
        """NUL is never legitimate in a DSN and remains rejected."""
        with pytest.raises(ValidationError) as excinfo:
            DatabaseConfig(alias="TEST", dsn="host:1521/svc\x00extra")
        assert "dsn" in str(excinfo.value)

        with pytest.raises(ValidationError) as excinfo:
            DatabaseUpdate(dsn="host:1521/svc\x00extra")
        assert "dsn" in str(excinfo.value)

    @pytest.mark.parametrize(
        "bad_dsn",
        [
            "host\n:1521/svc",  # embedded newline inside Easy Connect
            "host:1521\n/svc",
            "host\r:1521/svc",
            "ADB_HIGH\nSOMETHING_ELSE",  # newline inside TNS alias region
            "//host:1521/svc\nextra",  # line break in URL-form Easy Connect
        ],
        ids=[
            "easyconnect_embedded_lf",
            "easyconnect_split_between_port_and_service",
            "easyconnect_embedded_cr",
            "tns_alias_with_newline",
            "url_easyconnect_with_trailing_noise",
        ],
    )
    def test_dsn_rejects_linebreak_in_non_descriptor(self, bad_dsn: str):
        """Line breaks are only legitimate inside `(DESCRIPTION=...)` descriptors.

        For Easy Connect strings and TNS aliases, a line break is a user error
        (copy-paste mishap or similar) — fail fast with a clear validation
        error rather than silently rewriting it into something oracledb will
        mis-resolve.
        """
        with pytest.raises(ValidationError) as excinfo:
            DatabaseConfig(alias="TEST", dsn=bad_dsn)
        msg = str(excinfo.value)
        assert "dsn" in msg
        assert "connect descriptor" in msg

        with pytest.raises(ValidationError):
            DatabaseUpdate(dsn=bad_dsn)

    def test_dsn_trims_outer_whitespace(self):
        """Trailing whitespace (incl. newlines from clipboard) is silently trimmed.

        This keeps the common copy-paste mishap ergonomic while still rejecting
        embedded line breaks in non-descriptor DSNs.
        """
        dc = DatabaseConfig(alias="TEST", dsn="  host:1521/svc\n")
        assert dc.dsn == "host:1521/svc"

        u = DatabaseUpdate(dsn="\thost:1521/svc\r\n")
        assert u.dsn == "host:1521/svc"

    def test_dsn_trim_does_not_hide_internal_linebreaks(self):
        """Trim is only outer — internal line breaks still fail the descriptor check."""
        with pytest.raises(ValidationError):
            DatabaseConfig(alias="TEST", dsn="  host\n:1521/svc  ")

    def test_none_values_still_accepted(self):
        """Optional fields left as None must not trigger the validator."""
        dc = DatabaseConfig(alias="TEST")
        assert dc.password is None
        assert dc.username is None

    @pytest.mark.parametrize(
        "field,value",
        [
            ("password", 'p@ss/w0rd"hard!'),  # quotes, @, /, !
            ("dsn", "host:1521/service"),  # colons, slash
            ("config_dir", "/etc/oracle/network/admin"),  # absolute path
            ("wallet_location", "C:\\wallets\\prod"),  # Windows-style path
            ("username", "SYSTEM"),
            ("alias", "PROD_DB-01"),  # letters, digits, underscore, hyphen
        ],
    )
    def test_legitimate_values_still_accepted(self, field: str, value: str):
        """The validator must not reject ordinary credential/path values."""
        from server.app.core.secrets import reveal
        kwargs: dict[str, Any] = {"alias": "TEST", field: value}
        # Constructing succeeds and preserves the value verbatim.
        dc = DatabaseConfig(**kwargs)
        # ``password`` / ``wallet_password`` are stored as ``SecretStr``;
        # reveal them for the comparison.  Other fields pass through.
        assert reveal(getattr(dc, field)) == value


# ---------------------------------------------------------------------------
# Sensitive-field rendering: defaults to masked, opt-in reveal via context
# ---------------------------------------------------------------------------


class TestSensitiveFieldRendering:
    """Sensitive fields render as the masked sentinel by default."""

    def test_repr_is_masked(self):
        dc = DatabaseConfig(alias="TEST", password=SecretStr("hunter2"), wallet_password=SecretStr("walletpw"))
        assert "hunter2" not in repr(dc)
        assert "walletpw" not in repr(dc)

    def test_str_is_masked(self):
        dc = DatabaseConfig(alias="TEST", password=SecretStr("hunter2"), wallet_password=SecretStr("walletpw"))
        assert "hunter2" not in str(dc)
        assert "walletpw" not in str(dc)

    def test_default_dump_is_masked(self):
        dc = DatabaseConfig(alias="TEST", password=SecretStr("hunter2"), wallet_password=SecretStr("walletpw"))
        dumped = dc.model_dump()
        assert dumped["password"] == "**********"
        assert dumped["wallet_password"] == "**********"

    def test_default_dump_json_is_masked(self):
        dc = DatabaseConfig(alias="TEST", password=SecretStr("hunter2"), wallet_password=SecretStr("walletpw"))
        dumped_json = dc.model_dump_json()
        assert "hunter2" not in dumped_json
        assert "walletpw" not in dumped_json
        assert "**********" in dumped_json

    def test_reveal_context_unmasks(self):
        dc = DatabaseConfig(alias="TEST", password=SecretStr("hunter2"), wallet_password=SecretStr("walletpw"))
        dumped = dc.model_dump(context={REVEAL_KEY: True})
        assert dumped["password"] == "hunter2"
        assert dumped["wallet_password"] == "walletpw"

    def test_reveal_context_unmasks_json(self):
        dc = DatabaseConfig(alias="TEST", password=SecretStr("hunter2"), wallet_password=SecretStr("walletpw"))
        dumped_json = dc.model_dump_json(context={REVEAL_KEY: True})
        assert "hunter2" in dumped_json
        assert "walletpw" in dumped_json
        assert "**********" not in dumped_json

    def test_none_passes_through(self):
        dc = DatabaseConfig(alias="TEST")
        dumped = dc.model_dump()
        assert dumped["password"] is None
        assert dumped["wallet_password"] is None
