"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the top-level URL safety helpers.
"""
# spell-checker: disable

import os
import socket
import subprocess
import sys
from unittest.mock import AsyncMock

import httpx
import pytest

from url_safety import SafeAsyncClient, _PinnedBackend, validate_safe_url, validate_structural

# ---------------------------------------------------------------------------
# scheme + structural checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "ftp://example.com/",
        "data:text/plain,hello",
        "javascript:alert(1)",
        "",
        "not a url",
        "http://",
        "https://",
    ],
)
def test_rejects_disallowed_schemes_and_unparseable(url):
    """Only http/https with a host are permitted."""
    with pytest.raises(ValueError):
        validate_safe_url(url)


@pytest.mark.unit
def test_rejects_userinfo_in_url():
    """URLs carrying ``user:pass@host`` are not permitted."""
    with pytest.raises(ValueError):
        validate_safe_url("http://attacker@example.com/")
    with pytest.raises(ValueError):
        validate_safe_url("https://user:pass@example.com/")


@pytest.mark.unit
@pytest.mark.parametrize("port", [22, 25, 11434, 6379, 8086])
def test_rejects_non_standard_ports(monkeypatch, port):
    """Only standard web ports are permitted."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    with pytest.raises(ValueError):
        validate_safe_url(f"http://example.com:{port}/")


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "https://example.com/",
        "https://example.com:443/",
        "http://example.com:80/path?q=1",
        "https://example.com:8443/",
        "http://example.com:8080/",
    ],
)
def test_accepts_public_destinations(monkeypatch, url):
    """A public-resolving hostname on a permitted scheme/port is accepted."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    assert validate_safe_url(url) == url


# ---------------------------------------------------------------------------
# IP-literal deny-list
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.5.5.5/",
        "http://[::1]/",
        "http://169.254.169.254/",
        "http://[fe80::1]/",
        "http://10.0.0.1/",
        "http://10.255.255.255/",
        "http://172.16.0.1/",
        "http://172.31.1.1/",
        "http://192.168.1.1/",
        "http://[fc00::1]/",
        "http://[fd00::1]/",
        "http://0.0.0.0/",
        "http://[::]/",
        "http://224.0.0.1/",
        "http://[ff02::1]/",
        "http://255.255.255.255/",
        # IPv4-mapped IPv6 forms of the same private addresses
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://[::ffff:10.0.0.1]/",
    ],
)
def test_rejects_ip_literal_in_deny_ranges(url):
    """Literal IPs in any non-public range are rejected."""
    with pytest.raises(ValueError):
        validate_safe_url(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/",
        "https://1.1.1.1/",
        "http://93.184.216.34/",
        "http://[2606:4700:4700::1111]/",
    ],
)
def test_accepts_ip_literal_in_public_ranges(url):
    """Globally-routable IP literals are accepted."""
    assert validate_safe_url(url) == url


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        # 64:ff9b::/96 well-known NAT64 prefix encoding restricted IPv4s
        "http://[64:ff9b::a9fe:a9fe]/",  # 169.254.169.254
        "http://[64:ff9b::7f00:1]/",  # 127.0.0.1
        "http://[64:ff9b::a00:1]/",  # 10.0.0.1
        "http://[64:ff9b::c0a8:101]/",  # 192.168.1.1
        # 64:ff9b:1::/48 well-known local NAT64 prefix (RFC 8215) encoding 169.254.169.254
        "http://[64:ff9b:1:a9fe:a9:fe00::]/",
    ],
)
def test_rejects_nat64_embedded_restricted_ipv4(url):
    """Restricted IPv4 addresses tunneled through NAT64 prefixes are rejected."""
    with pytest.raises(ValueError):
        validate_safe_url(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        # ``::ffff:0:0:0/96`` — IPv4-translated (SIIT, RFC 2765/6052 §2.4)
        # — embeds the IPv4 destination in the lower 32 bits while
        # ``is_global=True``, so without an explicit decode the deny-list
        # would be bypassed.
        "http://[::ffff:0:a00:1]/",        # 10.0.0.1
        "http://[::ffff:0:7f00:1]/",       # 127.0.0.1
        "http://[::ffff:0:a9fe:a9fe]/",    # 169.254.169.254
        "http://[::ffff:0:c0a8:101]/",     # 192.168.1.1
    ],
)
def test_rejects_ipv4_translated_embedded_restricted_ipv4(url):
    """``::ffff:0:0:0/96`` literals must reject like other NAT64 prefixes do."""
    with pytest.raises(ValueError):
        validate_safe_url(url)
    with pytest.raises(ValueError):
        validate_structural(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        # ``::/96`` — IPv4-compatible IPv6 (RFC 4291 §2.5.5.1, deprecated).
        # ``is_global`` is True for the IPv6 form, so the embedded IPv4
        # has to be decoded explicitly.
        "http://[::127.0.0.1]/",
        "http://[::169.254.169.254]/",
        "http://[::10.0.0.1]/",
        "http://[::192.168.1.1]/",
    ],
)
def test_rejects_ipv4_compatible_embedded_restricted_ipv4(url):
    """``::a.b.c.d`` literals must reject when the embedded IPv4 is denied."""
    with pytest.raises(ValueError):
        validate_safe_url(url)
    with pytest.raises(ValueError):
        validate_structural(url)


@pytest.mark.unit
def test_accepts_ipv4_compatible_routable_ipv4():
    """An IPv4-compatible IPv6 literal whose embedded IPv4 is global is accepted."""
    assert validate_structural("http://[::8.8.8.8]/") == "http://[::8.8.8.8]/"


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://127。0。0。1/",         # U+3002 (CJK ideographic full stop)
        "http://169。254。169。254/",
        "http://127．0．0．1/",         # U+FF0E (fullwidth full stop)
        "http://10。0．0。1/",          # mixed U+3002 / U+FF0E
    ],
)
def test_rejects_fullwidth_dot_ipv4_literal(url):
    """Non-ASCII dot separators fold via UTS46 before the deny-list runs."""
    with pytest.raises(ValueError):
        validate_structural(url)
    with pytest.raises(ValueError):
        validate_safe_url(url)


@pytest.mark.unit
def test_accepts_nat64_embedded_routable_ipv4():
    """A NAT64 address whose embedded IPv4 is globally routable is accepted."""
    # 64:ff9b::8.8.8.8 = 64:ff9b::808:808
    assert validate_safe_url("http://[64:ff9b::808:808]/") == "http://[64:ff9b::808:808]/"


# ---------------------------------------------------------------------------
# validate_structural — same checks but no DNS resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://169.254.169.254/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://attacker@example.com/",
        "http://example.com:25/",
        "",
        "http://",
    ],
)
def test_validate_structural_rejects_obvious_bad(url):
    """Structural-only validation still rejects scheme/port/IP-literal violations."""
    with pytest.raises(ValueError):
        validate_structural(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        # Short-form, integer, octal, and hex aliases for 127.0.0.1
        "http://127.1/",
        "http://2130706433/",
        "http://0177.0.0.1/",
        "http://0x7f.0.0.1/",
        # 0.0.0.0 alias forms
        "http://0/",
        "http://0x0/",
        # 169.254.169.254 in alias forms
        "http://2852039166/",  # int form
        "http://0xa9.0xfe.0xa9.0xfe/",  # hex octets
    ],
)
def test_validate_structural_rejects_ipv4_alias_forms(url):
    """Non-canonical IPv4 aliases must canonicalize and hit the deny-list."""
    with pytest.raises(ValueError):
        validate_structural(url)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        # ``010.0.0.1`` is octal 8.0.0.1 to libc but decimal 10.0.0.1
        # to several HTTP/proxy resolvers — never let either disagree
        # decide the verdict, reject any non-canonical alias outright.
        "http://010.0.0.1/",
        "http://010.000.000.001/",
        "http://127.0.0.001/",
        # Single-integer form maps to a globally-routable IPv4 (8.8.8.8)
        # under libc but is not a real public hostname under most
        # resolvers — still ambiguous, still reject.
        "http://134744072/",
    ],
)
def test_rejects_non_canonical_ipv4_aliases_even_when_canonical_is_global(url):
    """Aliases that ``ipaddress`` rejects but ``inet_aton`` accepts must reject.

    The deny-list cannot rely on libc parsing matching the resolver
    that ultimately makes the connection. Any input outside canonical
    dotted-quad / IPv6 literal is treated as ambiguous and refused.
    """
    with pytest.raises(ValueError):
        validate_structural(url)
    with pytest.raises(ValueError):
        validate_safe_url(url)


@pytest.mark.unit
def test_validate_structural_accepts_hostname_without_dns(monkeypatch):
    """Structural validation never calls getaddrinfo, so it works without DNS."""

    def explode(*_args, **_kwargs):
        raise AssertionError("getaddrinfo must not be called by validate_structural")

    monkeypatch.setattr(socket, "getaddrinfo", explode)
    assert validate_structural("https://example.com/") == "https://example.com/"


# ---------------------------------------------------------------------------
# proxy environments — defer DNS resolution to the proxy
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_safe_async_client_skips_local_dns_when_proxied(monkeypatch):
    """A URL that would route via a proxy mount must not trigger local DNS.

    In proxy-only deployments only the proxy can resolve external
    names; a local getaddrinfo call would fail with NXDOMAIN even for
    a perfectly legitimate URL, and the previous httpx.AsyncClient code
    let the request through.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy.example.com:8080")

    def explode(*_args, **_kwargs):
        raise AssertionError("getaddrinfo must not be called for proxied URL")

    monkeypatch.setattr(socket, "getaddrinfo", explode)

    client = SafeAsyncClient(timeout=5.0)
    try:
        # Replace the proxy-mount transport with a MockTransport so we
        # can assert the request reaches it without booting a real
        # network connection.
        called = {"hit": False}

        def handler(request: httpx.Request) -> httpx.Response:
            called["hit"] = True
            assert request.url.host == "good.example.com"
            return httpx.Response(200, text="via-proxy")

        for pattern in list(client._client._mounts.keys()):  # noqa: SLF001
            if client._client._mounts[pattern] is not None:  # noqa: SLF001
                client._client._mounts[pattern] = httpx.MockTransport(handler)  # noqa: SLF001

        response = await client.get("https://good.example.com/")
        assert response.status_code == 200
        assert called["hit"]
        # Pin map remains empty — proxied URLs are not pinned because
        # the connection goes to the proxy host, not the destination.
        assert client.pins == {}
    finally:
        await client.aclose()


@pytest.mark.unit
async def test_safe_async_client_proxied_still_blocks_ip_literals(monkeypatch):
    """Even when proxied, IP-literal deny-list still applies before any I/O."""
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy.example.com:8080")
    client = SafeAsyncClient(timeout=5.0)
    try:
        with pytest.raises(ValueError):
            await client.get("http://169.254.169.254/opc/v2/")
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Happy Eyeballs — divide timeout across pinned IPs
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_pinned_backend_divides_timeout_across_ips():
    """Each attempt gets a per-IP slice of the total timeout, not the full budget."""
    pins = {"good.example.com": ["192.0.2.1", "192.0.2.2", "192.0.2.3"]}
    base = AsyncMock()
    timeouts_seen: list[float | None] = []

    async def record_then_succeed(_host, _port, *, timeout=None, **_kwargs):
        timeouts_seen.append(timeout)
        return "stream"

    base.connect_tcp = AsyncMock(side_effect=record_then_succeed)
    backend = _PinnedBackend(base, pins)

    await backend.connect_tcp("good.example.com", 443, timeout=9.0)

    # First (and only) attempt should have received ~ total / N.
    assert timeouts_seen[0] is not None
    assert timeouts_seen[0] <= 9.0 / 3 + 0.001


@pytest.mark.unit
async def test_safe_async_client_pins_idn_host_in_punycode_form(monkeypatch):
    """A Unicode hostname must be pinned under its IDNA / punycode form.

    httpx/httpcore connect with the IDNA (raw_host) form of the
    hostname; if the pin map is keyed off the raw Unicode string,
    PinnedBackend cannot find a match and the connection is rejected.
    """
    captured: dict[str, str] = {}

    def fake_getaddrinfo(host, _port, *_args, **_kwargs):
        captured["host"] = _decode_host(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.4.4", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="ok")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        await client.get("http://例え.テスト/")
        # The pin key must match what httpcore would pass on connect.
        assert "xn--r8jz45g.xn--zckzah" in client.pins
        assert client.pins["xn--r8jz45g.xn--zckzah"] == ["8.8.4.4"]
    # And the local DNS lookup must have used the ASCII form too.
    assert captured["host"] == "xn--r8jz45g.xn--zckzah"


@pytest.mark.unit
async def test_safe_async_client_pins_idn_using_httpx_idna(monkeypatch):
    """``faß.de`` must be pinned as ``xn--fa-hia.de`` (httpx/idna 2008).

    Python's stdlib idna codec follows IDNA 2003 and would map ß→ss,
    producing ``fass.de`` — a different DNS name than what httpx
    actually connects to. The pin key has to agree with httpx so
    PinnedBackend can match it.
    """

    def fake_getaddrinfo(host, _port, *_args, **_kwargs):
        assert _decode_host(host) == "xn--fa-hia.de"
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.4.4", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="ok")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        await client.get("http://faß.de/")
        assert "xn--fa-hia.de" in client.pins
        assert "fass.de" not in client.pins


@pytest.mark.unit
async def test_safe_async_client_resolves_via_anyio(monkeypatch):
    """SafeAsyncClient must use anyio.getaddrinfo so it does not block the loop.

    ``socket.getaddrinfo`` is synchronous; running it from an async
    handler stalls every other coroutine until the lookup completes.
    The previous httpx async client dispatched DNS through its async
    backend. Use ``anyio.getaddrinfo`` so behaviour is the same here.
    """
    import anyio as _anyio

    anyio_called = {"hit": False}

    async def fake_anyio_resolve(host, port, *_args, **_kwargs):
        del port
        anyio_called["hit"] = True
        assert host == "good.example.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.4.4", 0))]

    monkeypatch.setattr(_anyio, "getaddrinfo", fake_anyio_resolve)

    def explode(*_args, **_kwargs):
        raise AssertionError("synchronous socket.getaddrinfo would block the event loop")

    monkeypatch.setattr(socket, "getaddrinfo", explode)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="ok")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        await client.get("https://good.example.com/")
        assert anyio_called["hit"]


@pytest.mark.unit
async def test_pinned_backend_matches_idn_punycode_lookup():
    """PinnedBackend resolves hits when called with the punycode host."""
    pins = {"xn--r8jz45g.xn--zckzah": ["8.8.4.4"]}
    base = AsyncMock()
    base.connect_tcp = AsyncMock(return_value="stream")
    backend = _PinnedBackend(base, pins)

    await backend.connect_tcp("xn--r8jz45g.xn--zckzah", 443, timeout=5.0)

    base.connect_tcp.assert_awaited_once()
    assert base.connect_tcp.await_args.args[0] == "8.8.4.4"


@pytest.mark.unit
async def test_pinned_backend_single_ip_keeps_full_timeout():
    """A single pinned IP still receives the full requested timeout."""
    pins = {"good.example.com": ["192.0.2.1"]}
    base = AsyncMock()
    seen: list[float | None] = []

    async def record(_host, _port, *, timeout=None, **_kwargs):
        seen.append(timeout)
        return "stream"

    base.connect_tcp = AsyncMock(side_effect=record)
    backend = _PinnedBackend(base, pins)

    await backend.connect_tcp("good.example.com", 443, timeout=9.0)

    assert seen[0] == 9.0


# ---------------------------------------------------------------------------
# hostname resolution — restricted address class
# ---------------------------------------------------------------------------


def _fake_getaddrinfo(*ips: str):
    """Build a getaddrinfo replacement that returns the given addresses.

    Accepts both ``bytes`` and ``str`` host arguments because anyio
    encodes hostnames to bytes before calling socket.getaddrinfo on a
    worker thread.
    """

    def _resolver(host, port, *args, **kwargs):
        del host, port, args, kwargs
        results = []
        for ip in ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
            results.append((family, socket.SOCK_STREAM, 0, "", sockaddr))
        return results

    return _resolver


def _decode_host(host) -> str:
    """Normalise ``host`` (possibly bytes from anyio) to a lowercase string."""
    if isinstance(host, bytes):
        return host.decode("ascii").lower()
    return str(host).lower()


@pytest.mark.unit
def test_rejects_hostname_resolving_to_link_local_class(monkeypatch):
    """A hostname whose DNS answer falls into a restricted address class is rejected."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(ValueError):
        validate_safe_url("http://evil.example.com/")


@pytest.mark.unit
def test_rejects_hostname_resolving_to_loopback_class(monkeypatch):
    """Loopback class resolution is rejected even via hostname."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
    with pytest.raises(ValueError):
        validate_safe_url("http://localhost/")


@pytest.mark.unit
def test_rejects_hostname_resolving_to_restricted_class(monkeypatch):
    """A restricted address class is rejected even via hostname."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("10.1.2.3"))
    with pytest.raises(ValueError):
        validate_safe_url("http://internal.example.com/")


@pytest.mark.unit
def test_rejects_split_record(monkeypatch):
    """If any address in the answer set is restricted, the URL is rejected."""
    # One public address, one in a restricted class — the URL must still be rejected.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.4.4", "10.0.0.5"))
    with pytest.raises(ValueError):
        validate_safe_url("http://mixed.example.com/")


@pytest.mark.unit
def test_accepts_hostname_resolving_to_routable(monkeypatch):
    """A hostname whose every address is globally routable is accepted."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo("8.8.4.4", "2606:4700:4700::1111"),
    )
    assert validate_safe_url("https://good.example.com/") == "https://good.example.com/"


@pytest.mark.unit
def test_accepts_ascii_reg_name_invalid_under_idna(monkeypatch):
    """Hostnames with characters outside IDNA's grammar (e.g. underscores)
    are still accepted as long as the resolver returns a public address.

    The ``idna`` package rejects ``foo_bar`` because U+005F is not
    allowed in IDNA labels, but RFC 3986 reg-names and most resolvers
    accept underscores. httpx itself stores the lowercase ASCII form
    unchanged. The validator must follow that behaviour to avoid
    rejecting reachable URLs in no-proxy deployments.
    """
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.4.4"))
    assert validate_safe_url("https://foo_bar.example.com/") == "https://foo_bar.example.com/"


@pytest.mark.unit
async def test_safe_async_client_pins_ascii_reg_name(monkeypatch):
    """ASCII reg-name hostnames pin under their lowercase form.

    ``foo_bar.example`` is invalid under IDNA but httpx connects with
    the literal ASCII string. Without this, every fetch would fail
    after validation because the pin map would never receive an entry.
    """
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.4.4"))

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="ok")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        await client.get("https://Foo_Bar.example.com/")
        assert "foo_bar.example.com" in client.pins
        assert client.pins["foo_bar.example.com"] == ["8.8.4.4"]


@pytest.mark.unit
def test_rejects_hostname_unresolvable(monkeypatch):
    """A hostname that cannot be resolved is rejected (fail-closed)."""

    def _raise(*_args, **_kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    with pytest.raises(ValueError):
        validate_safe_url("http://nope.example.com/")


@pytest.mark.unit
def test_rejects_hostname_with_overlong_dns_label(monkeypatch):
    """``getaddrinfo`` may raise ``UnicodeError`` (not gaierror) for bad labels.

    UnicodeError happens to subclass ValueError, but its message
    ("label too long" / "label empty or too long") leaks the reason.
    The translation must produce the same generic "URL not permitted."
    text that every other rejection emits.
    """

    def _raise(*_args, **_kwargs):
        raise UnicodeError("label empty or too long")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    with pytest.raises(ValueError) as excinfo:
        validate_safe_url("http://" + ("a" * 70) + ".example.com/")
    assert str(excinfo.value) == "URL not permitted."


# ---------------------------------------------------------------------------
# validation errors stay generic
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "file:///etc/passwd",
        "http://attacker@example.com/",
    ],
)
def test_error_message_is_generic(url):
    """The raised message is identical across restricted address classes."""
    with pytest.raises(ValueError) as excinfo:
        validate_safe_url(url)
    msg = str(excinfo.value).lower()
    classifying_terms = ["169", "metadata", "loopback", "private", "rfc1918", "link-local", "ssrf"]
    for needle in classifying_terms:
        assert needle not in msg, f"Validation message classified the input as {needle!r}: {msg!r}"


# ---------------------------------------------------------------------------
# SafeAsyncClient: hop-by-hop revalidation
# ---------------------------------------------------------------------------


def _mock_transport(handler):
    """Build an httpx MockTransport from a request handler."""
    return httpx.MockTransport(handler)


@pytest.mark.unit
async def test_safe_async_client_blocks_redirect_to_denied_address(monkeypatch):
    """A 302 to a denied destination must raise rather than auto-follow."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "good.example.com":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/opc/v2/instance/"})
        return httpx.Response(200, text="should not be reached")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        with pytest.raises(ValueError):
            await client.get("http://good.example.com/")


@pytest.mark.unit
async def test_safe_async_client_follows_safe_redirect(monkeypatch):
    """A redirect chain that stays in public space is followed."""

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.example.com":
            return httpx.Response(302, headers={"Location": "https://second.example.com/page"})
        if request.url.host == "second.example.com":
            return httpx.Response(200, text="final body")
        return httpx.Response(404)

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        response = await client.get("http://first.example.com/")
        assert response.status_code == 200
        assert response.text == "final body"


@pytest.mark.unit
async def test_safe_async_client_blocks_initial_denied_target(monkeypatch):
    """The initial URL is validated before any request is issued."""
    sentinel = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        sentinel["called"] = True
        return httpx.Response(200)

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        with pytest.raises(ValueError):
            await client.get("http://127.0.0.1/")
    assert sentinel["called"] is False


@pytest.mark.unit
async def test_safe_async_client_rejects_malformed_redirect_location(monkeypatch):
    """A malformed Location must produce the neutral ValueError.

    ``httpx.URL.join`` raises ``httpx.InvalidURL`` (not a
    ``ValueError`` / ``HTTPError`` subclass) for inputs like
    ``http://[::1``; without an explicit translation that exception
    would leak as a 500.
    """
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.example.com":
            return httpx.Response(302, headers={"Location": "http://[::1"})
        return httpx.Response(200)

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        with pytest.raises(ValueError):
            await client.get("http://first.example.com/")


@pytest.mark.unit
async def test_safe_async_client_caps_redirects(monkeypatch):
    """An infinite redirect loop terminates with a ValueError."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": str(request.url)})

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        with pytest.raises(ValueError):
            await client.get("http://loop.example.com/")


@pytest.mark.unit
async def test_safe_async_client_stream_blocks_denied_redirect(monkeypatch):
    """The streaming entry point applies the same hop-by-hop check."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.example.com":
            return httpx.Response(302, headers={"Location": "http://10.0.0.1/secret"})
        return httpx.Response(200, text="x")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        with pytest.raises(ValueError):
            async with client.stream("GET", "http://first.example.com/"):
                pass


@pytest.mark.unit
async def test_safe_async_client_stream_yields_final_response(monkeypatch):
    """Non-redirecting stream returns the response body to the caller."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="streamed body")

    async with (
        SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client,
        client.stream("GET", "http://only.example.com/") as response,
    ):
        assert response.status_code == 200
        chunks = [chunk async for chunk in response.aiter_bytes()]
        assert b"".join(chunks) == b"streamed body"


# ---------------------------------------------------------------------------
# IP pinning — connection target equals the validated address
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_pinned_backend_routes_to_pinned_ip():
    """connect_tcp on a pinned host is delegated to the validated IP."""
    pins: dict[str, list[str]] = {"good.example.com": ["8.8.8.8"]}
    base = AsyncMock()
    base.connect_tcp = AsyncMock(return_value="stream-stub")
    backend = _PinnedBackend(base, pins)

    result = await backend.connect_tcp("good.example.com", 443, timeout=5.0)

    assert result == "stream-stub"
    base.connect_tcp.assert_awaited_once()
    call_args = base.connect_tcp.await_args
    # Positional or keyword — assert the IP is what was passed.
    passed_host = call_args.args[0] if call_args.args else call_args.kwargs.get("host")
    assert passed_host == "8.8.8.8"


@pytest.mark.unit
async def test_pinned_backend_refuses_unknown_host():
    """A host that was never validated cannot be reached."""
    base = AsyncMock()
    base.connect_tcp = AsyncMock()
    backend = _PinnedBackend(base, {"good.example.com": ["8.8.8.8"]})

    with pytest.raises(ConnectionError):
        await backend.connect_tcp("rebound.example.com", 443, timeout=5.0)
    base.connect_tcp.assert_not_awaited()


@pytest.mark.unit
async def test_pinned_backend_lookup_is_case_insensitive():
    """Hostname matching ignores case (httpx may lowercase the URL host)."""
    base = AsyncMock()
    base.connect_tcp = AsyncMock(return_value="stream")
    backend = _PinnedBackend(base, {"good.example.com": ["8.8.8.8"]})

    await backend.connect_tcp("Good.Example.COM", 443)

    base.connect_tcp.assert_awaited_once()
    passed_host = base.connect_tcp.await_args.args[0]
    assert passed_host == "8.8.8.8"


@pytest.mark.unit
async def test_pinned_backend_falls_back_to_next_ip_on_failure():
    """When the first pinned IP refuses, the next one is tried.

    Mirrors what httpx/AnyIO did before pinning: walk all DNS answers
    until one succeeds. Without this, a multi-record host whose first
    record is unreachable would now fail outright.
    """
    pins = {"good.example.com": ["192.0.2.1", "8.8.8.8"]}
    base = AsyncMock()
    base.connect_tcp = AsyncMock(
        side_effect=[ConnectionRefusedError("first refused"), "stream-stub"]
    )
    backend = _PinnedBackend(base, pins)

    result = await backend.connect_tcp("good.example.com", 443, timeout=5.0)

    assert result == "stream-stub"
    assert base.connect_tcp.await_count == 2
    first_call = base.connect_tcp.await_args_list[0]
    second_call = base.connect_tcp.await_args_list[1]
    assert first_call.args[0] == "192.0.2.1"
    assert second_call.args[0] == "8.8.8.8"


@pytest.mark.unit
async def test_pinned_backend_raises_when_every_ip_fails():
    """If every pinned IP fails, the last error is re-raised."""
    pins = {"good.example.com": ["192.0.2.1", "192.0.2.2"]}
    base = AsyncMock()
    last_err = ConnectionRefusedError("the second one")
    base.connect_tcp = AsyncMock(
        side_effect=[ConnectionRefusedError("the first one"), last_err]
    )
    backend = _PinnedBackend(base, pins)

    with pytest.raises(ConnectionRefusedError) as excinfo:
        await backend.connect_tcp("good.example.com", 443)
    assert excinfo.value is last_err


@pytest.mark.unit
async def test_pinned_backend_passes_through_other_methods():
    """sleep / connect_unix_socket are forwarded to the base backend."""
    base = AsyncMock()
    base.sleep = AsyncMock()
    base.connect_unix_socket = AsyncMock(return_value="uds-stream")
    backend = _PinnedBackend(base, {})

    await backend.sleep(0.1)
    result = await backend.connect_unix_socket("/tmp/sock")

    assert result == "uds-stream"
    base.sleep.assert_awaited_once_with(0.1)


@pytest.mark.unit
async def test_safe_async_client_pins_each_resolved_host(monkeypatch):
    """SafeAsyncClient populates the pins dict during URL validation."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.4.4"))

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="ok")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        await client.get("https://good.example.com/page")
        assert client.pins["good.example.com"] == ["8.8.4.4"]


@pytest.mark.unit
async def test_safe_async_client_pins_every_dns_answer(monkeypatch):
    """All validated answers are pinned, not just the first."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo("8.8.4.4", "1.1.1.1", "2606:4700:4700::1111"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="ok")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        await client.get("https://multi.example.com/")
        assert client.pins["multi.example.com"] == ["8.8.4.4", "1.1.1.1", "2606:4700:4700::1111"]


@pytest.mark.unit
async def test_safe_async_client_honours_https_proxy_env(monkeypatch):
    """Production construction picks up env-driven HTTPS_PROXY mounts.

    The check is structural — we don't issue a request — because httpx
    builds the proxy transport at AsyncClient construction time. If
    ``HTTPS_PROXY`` is set, the client must own a mount for that
    proxy; without it, web ingestion would silently bypass mandatory
    egress in proxy-only deployments.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy.example.com:8080")
    client = SafeAsyncClient(timeout=5.0)
    try:
        # AsyncClient stores per-pattern mounts in `_mounts`; the
        # presence of any mount whose value differs from the default
        # transport is enough to confirm proxy discovery happened.
        mounts = client._client._mounts  # noqa: SLF001
        proxy_mounts = [
            t for t in mounts.values()
            if t is not None and t is not client._client._transport  # noqa: SLF001
        ]
        assert proxy_mounts, "expected env HTTPS_PROXY to register a mount"
    finally:
        await client.aclose()


@pytest.mark.unit
async def test_safe_async_client_pins_only_default_transport(monkeypatch):
    """Pinning is installed on the no-proxy transport, not on proxy mounts.

    Proxy transports send the request to the proxy host (which runs
    its own egress controls), so destination-IP pinning does not apply
    to those mounts.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy.example.com:8080")
    client = SafeAsyncClient(timeout=5.0)
    try:
        default_transport = client._client._transport  # noqa: SLF001
        assert isinstance(default_transport, httpx.AsyncHTTPTransport)
        assert isinstance(default_transport._pool._network_backend, _PinnedBackend)  # noqa: SLF001
        for transport in client._client._mounts.values():  # noqa: SLF001
            if transport is None or transport is default_transport:
                continue
            assert not isinstance(
                getattr(getattr(transport, "_pool", None), "_network_backend", None),
                _PinnedBackend,
            ), "proxy mounts must not be pinned"
    finally:
        await client.aclose()


@pytest.mark.unit
async def test_safe_async_client_pins_each_redirect_target(monkeypatch):
    """Each redirect hop adds its destination to the pin map."""
    resolutions = iter(["8.8.4.4", "1.1.1.1"])
    fake_pool = {host: next(resolutions) for host in ("first.example.com", "second.example.com")}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        del port, args, kwargs
        ip = fake_pool[_decode_host(host)]
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.example.com":
            return httpx.Response(302, headers={"Location": "https://second.example.com/end"})
        return httpx.Response(200, text="done")

    async with SafeAsyncClient(timeout=5.0, transport=_mock_transport(handler)) as client:
        await client.get("https://first.example.com/")
        assert client.pins == {
            "first.example.com": ["8.8.4.4"],
            "second.example.com": ["1.1.1.1"],
        }


# ---------------------------------------------------------------------------
# client/server decoupling — url_safety must be importable on its own
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_url_safety_import_does_not_pull_in_server_app():
    """A fresh interpreter that imports ``url_safety`` must not load server.app.

    The Streamlit client tab reads ``validate_safe_url`` from this
    module. In a client-only install (``ai-optimizer[client]``) the
    server package is shipped but its runtime extras (langchain-oracledb
    etc.) are not, so any transitive load of ``server.app.__init__``
    would fail at import time and break the UI tab. Subprocess so
    ``sys.modules`` does not already hold the server package from the
    surrounding test session.
    """
    src_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    snippet = (
        "import sys, url_safety\n"
        "leaked = [k for k in sys.modules if k.startswith('server')]\n"
        "print('OK' if not leaked else 'LEAKED:' + ','.join(leaked))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=src_root,
        env={**os.environ, "PYTHONPATH": src_root, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "OK", proc.stdout + proc.stderr
