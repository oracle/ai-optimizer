"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Logging filter that redacts sensitive field values from formatted log messages.
"""

import logging
import re
from typing import Iterable

# Static fallback used when the canonical schemas can't be imported (see the
# lazy-import path in ``_sensitive_keys``). Kept in sync with the schema-derived
# set; the import path is preferred so that adding a new sensitive field in a
# schema is automatically picked up.
_STATIC_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        # Schema fields (lowercase, as used in JSON / Pydantic dumps)
        "password",
        "wallet_password",
        "key_content",
        "pass_phrase",
        "api_key",
        # Settings flat aliases (lowercase, as field names)
        "db_password",
        "db_wallet_password",
        "oci_cli_passphrase",
        "oci_cli_key_content",
        # Env-var forms (uppercase, as they appear in os.environ dumps,
        # .env files, subprocess output, etc.). Word-boundary matching means
        # AIO_DB_PASSWORD would not match if only ``db_password`` were listed
        # — these aliases close that gap.
        "AIO_API_KEY",
        "AIO_DB_PASSWORD",
        "AIO_DB_WALLET_PASSWORD",
        "AIO_OCI_CLI_PASSPHRASE",
        "AIO_OCI_CLI_KEY_CONTENT",
        "DB_PASSWORD",
        "DB_WALLET_PASSWORD",
        # Per-provider API key env vars (and AIO_-prefixed forms) used by the
        # model registry's env-override path.  Listed explicitly because the
        # word-boundary check prevents ``api_key`` from matching ``API_KEY``
        # inside ``OPENAI_API_KEY``.
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "PPLX_API_KEY",
        "AIO_OPENAI_API_KEY",
        "AIO_COHERE_API_KEY",
        "AIO_PPLX_API_KEY",
        # HTTP auth header.  ``api_key`` would not match ``API-Key`` (hyphen
        # rather than underscore), so the header form is listed separately.
        "X-API-Key",
    }
)


def _sensitive_keys() -> tuple[frozenset[str], str]:
    """Return the active sensitive-key set and its provenance.

    ``logging_config`` is shared by server and client packages.  Falling back
    to the static set keeps client-only deployments importable even if the
    server modules aren't on the path (test envs, packaging splits).
    """
    # Imports must remain function-local: ``server/__init__.py`` runs
    # ``configure_logging`` at package-load time, which imports
    # ``RedactingFilter`` from this module. Hoisting the schema imports
    # to module top would close the cycle (logging_redaction →
    # server.app.* → server/__init__.py → logging_config →
    # logging_redaction) and leave ``RedactingFilter`` undefined when
    # the inner import resolves.
    try:
        from server.app.database.schemas import DatabaseSensitive  # noqa: PLC0415
        from server.app.models.defaults import ENV_OVERRIDES  # noqa: PLC0415
        from server.app.models.schemas import ModelSensitive  # noqa: PLC0415
        from server.app.oci.schemas import OciSensitive  # noqa: PLC0415
    except ImportError:
        return _STATIC_SENSITIVE_KEYS, "static"

    keys: set[str] = set()
    for cls in (DatabaseSensitive, OciSensitive, ModelSensitive):
        keys.update(cls.model_fields.keys())
    # Public identifier and path; not credential material.
    keys.discard("fingerprint")
    keys.discard("security_token_file")
    keys.update(
        {
            "db_password",
            "db_wallet_password",
            "oci_cli_passphrase",
            "oci_cli_key_content",
        }
    )
    keys.update(
        {
            "AIO_API_KEY",
            "AIO_DB_PASSWORD",
            "AIO_DB_WALLET_PASSWORD",
            "AIO_OCI_CLI_PASSPHRASE",
            "AIO_OCI_CLI_KEY_CONTENT",
            "DB_PASSWORD",
            "DB_WALLET_PASSWORD",
            "X-API-Key",
        }
    )
    # Per-provider env-var aliases derived from the env-override registry.
    # Adding a provider in ``defaults.ENV_OVERRIDES`` automatically extends
    # the keyset; both the bare form and the AIO_ prefix form are included
    # because ``apply_env_overrides`` accepts either.
    for env_var, _provider, field in ENV_OVERRIDES:
        if field == "api_key":
            keys.add(env_var)
            keys.add(f"AIO_{env_var}")
    return frozenset(keys), "schemas"


REDACTED = "<redacted>"


def _build_kv_pattern(keys: Iterable[str]) -> re.Pattern[str]:
    """Compile the key/value redaction pattern for *keys*.

    ``q`` captures an optional surrounding quote so JSON-style
    (``"api_key": ...``), Python-repr-style (``'api_key': ...``), and
    bare-style (``api_key=...``) keys all match.  The named backreference
    ``(?P=q)`` requires the closing quote to match the opening (both empty,
    both ``"``, or both ``'``), rejecting mismatched quoting.

    ``\\b`` enforces word-boundary so ``password`` doesn't match inside
    ``xpassword``.

    Value branches, in order:

    1. ``"..."`` / ``'...'`` — quoted strings.  ``\\.`` consumes any
       backslash-escape so a value containing an escaped quote
       (``"abc\\"def"``) does not terminate the match at the inner quote.
    2. ``-----BEGIN ... -----END ...-----`` — PEM-style cryptographic blocks
       captured as a whole; the lazy ``[\\s\\S]+?`` spans embedded newlines.
    3. ``[^\\n,;}\\)]+`` — single-line unquoted values, including internal
       spaces (so ``password=my secret value`` is captured in full rather
       than truncated at the first whitespace).
    """
    alt = "|".join(re.escape(k) for k in keys)
    return re.compile(
        rf"(?P<q>[\"']?)(?P<k>\b(?:{alt})\b)(?P=q)"
        rf"(?P<sep>\s*[:=]\s*)"
        rf"(?P<v>"
        rf"\"(?:\\.|[^\"\\])*\""
        rf"|'(?:\\.|[^'\\])*'"
        rf"|-----BEGIN[A-Z0-9 \-]+-----[\s\S]+?-----END[A-Z0-9 \-]+-----"
        rf"|[^\n,;}}\)]+"
        rf")",
        re.IGNORECASE,
    )


# Connection-string credentials: scheme://user:value@host
_DSN_CRED = re.compile(r"(?P<pre>[a-zA-Z][\w+.-]*://[^:/\s]+:)[^@\s]+(?P<post>@)")

# SQL ``IDENTIFIED BY <secret>`` (e.g. CREATE/ALTER USER or END USER DDL). The
# secret takes one of three forms (matched in this order):
#   1. ``VALUES '<verifier-hash>'`` — a pre-computed password hash (single-quoted
#      literal, doubled quotes allowed). Tried first so the bare-identifier branch
#      does not match the ``VALUES`` keyword and leave the hash exposed.
#   2. ``"<quoted identifier>"`` — a double-quoted password.
#   3. ``<bare identifier>`` — an unquoted password, which Oracle requires to be a
#      valid identifier, so this matches that grammar rather than ``\S+`` (which
#      would over-consume unrelated tokens).
# It is not a key=value pair, so the KV pattern above does not cover it.
_IDENTIFIED_BY = re.compile(
    r"(?P<pre>IDENTIFIED\s+BY\s+)"
    r"(?:VALUES\s+'(?:[^']|'')*'"
    r'|"(?:[^"]|"")*"'
    r"|[A-Za-z][A-Za-z0-9_$#]*)",
    re.IGNORECASE,
)


class RedactingFilter(logging.Filter):
    """Replace sensitive field values in log records with ``<redacted>``.

    The filter mutates ``record.msg`` and clears ``record.args`` so any handler
    downstream sees the scrubbed text.  ``key_count`` and ``key_source`` are
    exposed as attributes so a caller (typically ``logging_config``) can emit
    a one-time observability line *after* ``dictConfig`` returns; the filter
    deliberately does no logging during ``__init__`` because ``dictConfig``
    constructs filters before the new handlers are fully active.
    """

    def __init__(self) -> None:
        super().__init__()
        keys, source = _sensitive_keys()
        self.key_count = len(keys)
        self.key_source = source
        self._kv = _build_kv_pattern(keys)

    def scrub(self, text: str) -> str:
        # Preserve the surrounding quote (empty for bare keys, ``"`` or ``'``
        # for quoted keys) so the redacted line keeps its original shape.
        text = self._kv.sub(lambda m: f"{m['q']}{m['k']}{m['q']}{m['sep']}{REDACTED}", text)
        text = _DSN_CRED.sub(lambda m: f"{m['pre']}{REDACTED}{m['post']}", text)
        text = _IDENTIFIED_BY.sub(lambda m: f"{m['pre']}{REDACTED}", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        scrubbed = self.scrub(msg)
        if scrubbed != msg:
            record.msg = scrubbed
            record.args = ()
        return True
