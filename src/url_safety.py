"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

URL eligibility helpers for user-provided fetch destinations.

Redirects are handled manually and each target is validated before
retrieval. Two layers:

* :func:`validate_safe_url` is a pure-Python check that only http/https
  with a globally-routable host is accepted, applied to every address in
  the DNS answer set.
* :class:`SafeAsyncClient` wraps :class:`httpx.AsyncClient` with
  ``follow_redirects=False`` and revalidates each ``Location`` hop. It
  also pins the underlying TCP connection to the address resolved at
  validation time, so a second DNS lookup at connection time cannot
  return a different answer.

Address eligibility is decided against ``ipaddress`` classifications
(globally-routable + non-multicast). A single generic error message is
raised on every refusal.
"""
# spell-checker:ignore getaddrinfo gaierror httpcore punycode

from __future__ import annotations

import contextlib
import ipaddress
import socket
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import anyio
import httpcore
import httpx
import idna

if TYPE_CHECKING:
    from collections.abc import Iterable

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_REDIRECTS = 5
_REJECT_MESSAGE = "URL cannot be used for this import."
# Floor on the per-IP connect deadline so a busy host with many DNS
# answers still has a usable budget for each individual attempt.
_MIN_PER_ATTEMPT_TIMEOUT = 1.0

# IPv6 prefixes that carry an IPv4 value in the lower 32 bits. Decode
# these forms before applying address classification so translated
# destinations are evaluated consistently.
_NAT64_WELL_KNOWN_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")
# RFC 2765 / RFC 6052 §2.4 IPv4-translated address — note the extra
# zero group versus the IPv4-mapped ``::ffff:0:0/96`` that Python
# already recognises via ``IPv6Address.ipv4_mapped``.
_IPV4_TRANSLATED_PREFIX = ipaddress.IPv6Network("::ffff:0:0:0/96")
# RFC 4291 §2.5.5.1 IPv4-compatible IPv6 (deprecated) — ``::a.b.c.d``
# carries the IPv4 value in the lower 32 bits with no distinguishing
# prefix bytes. Disjoint from the prefixes above.
_IPV4_COMPATIBLE_PREFIX = ipaddress.IPv6Network("::/96")


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """Return the IPv4 destination encoded in *addr*, or None.

    Recognises the IPv4-mapped form (``::ffff:0:0/96``), the
    IPv4-translated form (``::ffff:0:0:0/96``), the RFC 6052
    well-known NAT64 prefix (``64:ff9b::/96``), and the deprecated
    IPv4-compatible form (``::/96``). Custom NAT64 prefixes are
    operator-specific; sites that route them must apply egress
    controls at the translator itself.
    """
    if addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    if (
        addr in _NAT64_WELL_KNOWN_PREFIX
        or addr in _IPV4_TRANSLATED_PREFIX
        or addr in _IPV4_COMPATIBLE_PREFIX
    ):
        return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return None


def _is_address_denied(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *addr* is not eligible as a fetch destination."""
    # ``is_global`` is False for the non-routable classes covered by
    # ``ipaddress`` (the various reserved / unspecified / link-local
    # blocks, plus the documented private ranges). Multicast addresses
    # report ``is_global=True`` (e.g. 224.0.0.1) so they are excluded
    # separately, and IPv6 addresses that tunnel an IPv4 destination via
    # ``::ffff:`` or ``64:ff9b::`` are evaluated against the embedded v4.
    if isinstance(addr, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(addr)
        if embedded is not None:
            addr = embedded
    if addr.is_multicast:
        return True
    return not addr.is_global


def _coerce_to_ip_literal(bare_host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Canonicalise *bare_host* if it is a canonical IPv4 / IPv6 literal.

    Returns ``None`` for hostnames. IPv4-looking inputs accepted by
    legacy parsers (``socket.inet_aton`` short ``127.1``, integer
    ``2130706433``, octal ``010.0.0.1``, hex ``0x7f.0.0.1``) but not
    by the canonical parser are treated as invalid because different
    stacks can interpret them differently — ``010.0.0.1`` is octal
    ``8.0.0.1`` under ``inet_aton`` but decimal ``10.0.0.1`` in
    several HTTP / proxy URL parsers.

    Non-ASCII hostnames are folded through IDNA UTS46 first, so
    fullwidth (U+FF0E) or ideographic (U+3002) dot separators (e.g.
    ``127。0。0。1``) collapse to the same canonical IPv4 that httpx
    will hand to the transport.
    """
    try:
        return ipaddress.ip_address(bare_host)
    except ValueError:
        pass
    candidate = bare_host
    try:
        candidate.encode("ascii")
    except UnicodeEncodeError:
        try:
            candidate = idna.encode(bare_host, uts46=True).decode("ascii")
        except (idna.IDNAError, UnicodeError, UnicodeDecodeError):
            return None
        try:
            return ipaddress.ip_address(candidate)
        except ValueError:
            pass
    try:
        socket.inet_aton(candidate)
    except OSError:
        return None
    # ``inet_aton`` accepted the input but the strict canonical parser
    # didn't — this is one of the historical IPv4 alias forms whose
    # parsing is resolver-dependent. Refuse outright instead of
    # picking a canonical class that the actual fetch path may not
    # agree with.
    raise ValueError(_REJECT_MESSAGE)


def _idna_host(host: str) -> str:
    """Return the lowercase host string in the form httpx will connect with.

    * IP literals: bracket-stripped lowercase.
    * ASCII reg-names: lowercase pass-through. RFC 3986 reg-names accept
      characters that IDNA rejects (most notably ``_``); httpx itself
      stores those unchanged in ``raw_host``, and resolvers may
      legitimately resolve them, so the validator must not reject them.
    * Non-ASCII (IDN) hostnames: encoded via the third-party ``idna``
      package (IDNA 2008), which is the same library httpx uses. Python's
      stdlib ``idna`` codec implements IDNA 2003 and would map e.g.
      ``faß.de`` → ``fass.de``, a different DNS name than the
      ``xn--fa-hia.de`` httpx connects to.

    Hosts that fail IDNA encoding raise :class:`ValueError` so the
    caller's neutral rejection translation still applies.
    """
    bare = host.strip("[]")
    try:
        ipaddress.ip_address(bare)
        return bare.lower()
    except ValueError:
        pass
    try:
        bare.encode("ascii")
    except UnicodeEncodeError:
        try:
            return idna.encode(bare).decode("ascii").lower()
        except (idna.IDNAError, UnicodeError, UnicodeDecodeError) as ex:
            raise ValueError(_REJECT_MESSAGE) from ex
    return bare.lower()


def _addresses_from_getaddrinfo(infos: list) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Project ``getaddrinfo`` rows into a list of validated address objects."""
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        if family == socket.AF_INET:
            addresses.append(ipaddress.IPv4Address(sockaddr[0]))
        elif family == socket.AF_INET6:
            addresses.append(ipaddress.IPv6Address(sockaddr[0]))
    if not addresses:
        raise ValueError(_REJECT_MESSAGE)
    return addresses


def _resolve_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Return every address ``getaddrinfo`` reports for *host* (synchronous)."""
    try:
        infos = socket.getaddrinfo(_idna_host(host), None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as ex:
        # ``UnicodeError`` covers overlong DNS labels and IDNA encoding
        # failures — those subclass ValueError too, but their message
        # leaks the reason and they would otherwise bypass the generic
        # rejection translation that callers depend on.
        raise ValueError(_REJECT_MESSAGE) from ex
    return _addresses_from_getaddrinfo(infos)


async def _resolve_addresses_async(
    host: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Async variant of :func:`_resolve_addresses` for the async hot path.

    ``socket.getaddrinfo`` is blocking. Calling it from an async
    handler stalls every other coroutine on the same loop until the
    DNS round-trip completes. ``anyio.getaddrinfo`` dispatches the
    lookup to the loop's thread pool so the loop stays responsive.
    """
    try:
        infos = await anyio.getaddrinfo(_idna_host(host), None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as ex:
        raise ValueError(_REJECT_MESSAGE) from ex
    return _addresses_from_getaddrinfo(infos)


def _resolve_and_validate(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve *host* and require every address to pass the deny-list."""
    addresses = _resolve_addresses(host)
    for addr in addresses:
        if _is_address_denied(addr):
            raise ValueError(_REJECT_MESSAGE)
    return addresses


async def _resolve_and_validate_async(
    host: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Async :func:`_resolve_and_validate` for SafeAsyncClient."""
    addresses = await _resolve_addresses_async(host)
    for addr in addresses:
        if _is_address_denied(addr):
            raise ValueError(_REJECT_MESSAGE)
    return addresses


def validate_structural(url: str) -> str:
    """Return *url* if scheme/port/host shape and literal address classification pass.

    Same checks as :func:`validate_safe_url` but never calls
    ``getaddrinfo``. Useful for environments where the application host
    has no external DNS access (proxy-only egress) — scheme, port,
    userinfo, and IP-literal classification still apply without
    needing to resolve hostnames.
    """
    if not isinstance(url, str) or not url:
        raise ValueError(_REJECT_MESSAGE)

    try:
        parts = urlsplit(url)
    except ValueError as ex:
        raise ValueError(_REJECT_MESSAGE) from ex

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(_REJECT_MESSAGE)

    if parts.username is not None or parts.password is not None:
        raise ValueError(_REJECT_MESSAGE)

    host = parts.hostname
    if not host:
        raise ValueError(_REJECT_MESSAGE)

    try:
        port = parts.port
    except ValueError as ex:
        raise ValueError(_REJECT_MESSAGE) from ex
    effective_port = port if port is not None else _DEFAULT_PORTS[parts.scheme.lower()]
    if effective_port not in _ALLOWED_PORTS:
        raise ValueError(_REJECT_MESSAGE)

    # If the host parses as a canonical or alias IP literal, validate
    # it directly. ``_coerce_to_ip_literal`` accepts non-canonical
    # forms (``127.1``, ``2130706433``, octal/hex octets) so the
    # deny-list still catches them when the structural-only path is
    # the last guard before I/O.
    bare_host = host.strip("[]")
    canonical = _coerce_to_ip_literal(bare_host)
    if canonical is None:
        return url
    if _is_address_denied(canonical):
        raise ValueError(_REJECT_MESSAGE)
    return url


def validate_safe_url(url: str) -> str:
    """Return *url* if it is an eligible fetch target; raise :class:`ValueError` otherwise.

    Eligibility means: scheme is http/https, host is present, no
    userinfo, port is in the standard web set, and *every* address the
    host resolves to (or, if the host is an IP literal, the literal
    itself) is globally routable.
    """
    validate_structural(url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    bare_host = host.strip("[]")
    if _coerce_to_ip_literal(bare_host) is None:
        # Hostname — resolve and re-check every answer. IP literals /
        # alias forms were already vetted by validate_structural.
        _resolve_and_validate(host)
    return url


def _pin_targets_for_literal(bare_host: str) -> tuple[str, list[str]] | None:
    """Return ``(host_key, [canonical_ip])`` if *bare_host* is an IP literal."""
    canonical = _coerce_to_ip_literal(bare_host)
    if canonical is None:
        return None
    if _is_address_denied(canonical):
        raise ValueError(_REJECT_MESSAGE)
    # Use the original host form (lowercased) as the pin key so
    # ``_PinnedBackend`` can look it up against whatever httpcore
    # passes; the value list holds the canonical IP that the connect
    # step will actually reach.
    return bare_host.lower(), [str(canonical)]


def _hostname_for_pin(url: str) -> tuple[str, list[str]]:
    """Synchronous variant: resolve the host via :mod:`socket`."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    bare = host.strip("[]")
    literal = _pin_targets_for_literal(bare)
    if literal is not None:
        return literal
    addrs = _resolve_and_validate(host)
    return _idna_host(host), [str(a) for a in addrs]


async def _hostname_for_pin_async(url: str) -> tuple[str, list[str]]:
    """Async variant of :func:`_hostname_for_pin` for the async hot path."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    bare = host.strip("[]")
    literal = _pin_targets_for_literal(bare)
    if literal is not None:
        return literal
    addrs = await _resolve_and_validate_async(host)
    return _idna_host(host), [str(a) for a in addrs]


def _resolve_redirect(current: str, location: str) -> str:
    """Resolve *location* against *current*, translating malformed inputs.

    ``httpx.URL.join`` raises :class:`httpx.InvalidURL` for malformed
    targets such as ``http://[::1`` (truncated bracket / invalid port).
    That exception is *not* a ``ValueError`` / ``HTTPError`` subclass,
    so without this translation it would leak through the redirect
    loop and become a 500 instead of the neutral rejection.
    """
    try:
        return str(httpx.URL(current).join(location))
    except httpx.InvalidURL as ex:
        raise ValueError(_REJECT_MESSAGE) from ex


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Route direct TCP connects through the validation-time address set.

    Every call to ``connect_tcp`` walks the validated address list for
    the requested host and returns the first connection that succeeds.
    Host keys missing from the map receive the module-level rejection;
    this is also what happens once the ``_MAX_REDIRECTS`` ceiling has
    been crossed.
    """

    def __init__(self, base: httpcore.AsyncNetworkBackend, pins: dict[str, list[str]]) -> None:
        self._base = base
        self._pins = pins

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        ips = self._pins.get(host.lower())
        if not ips:
            raise ConnectionError(_REJECT_MESSAGE)
        # When more than one IP is pinned, divide the deadline so a
        # blackholed first address can't burn the entire budget. This
        # bounds the worst-case wait at roughly the original timeout.
        if timeout is not None and len(ips) > 1:
            per_attempt: float | None = max(timeout / len(ips), _MIN_PER_ATTEMPT_TIMEOUT)
        else:
            per_attempt = timeout
        last_error: BaseException | None = None
        for ip in ips:
            try:
                return await self._base.connect_tcp(
                    ip,
                    port,
                    timeout=per_attempt,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (OSError, httpcore.ConnectError, httpcore.ConnectTimeout) as ex:
                # OSError covers ConnectionRefusedError, TimeoutError,
                # and the assorted host-unreachable variants — try the
                # next validated address before giving up.
                last_error = ex
                continue
        assert last_error is not None  # loop entered with at least one ip
        raise last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._base.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self._base.sleep(seconds)


class SafeAsyncClient:
    """Async HTTP client that revalidates every URL it touches.

    ``follow_redirects`` is forced off and each ``Location`` is
    re-validated through :func:`validate_safe_url` before the next
    request is issued. The hop count is capped at five.

    For production callers (no ``transport`` argument), the underlying
    connection pool is wired through :class:`_PinnedBackend` so that
    ``connect_tcp`` is satisfied only via the IP recorded during
    validation. A custom *transport* may be supplied for testing.
    """

    def __init__(self, timeout: float = 60.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._pins: dict[str, list[str]] = {}
        if transport is None:
            # Let httpx own the AsyncClient construction so env-driven
            # ``HTTP_PROXY`` / ``HTTPS_PROXY`` mounts are still
            # discovered; passing ``transport=`` would suppress that
            # discovery. Pinning is then installed on the default
            # (no-proxy) transport only — proxy mounts hand the request
            # off to a proxy server which performs the actual egress
            # under its own controls, so destination-IP pinning would
            # not apply there.
            self._client = httpx.AsyncClient(follow_redirects=False, timeout=timeout)
            default_transport = self._client._transport  # noqa: SLF001
            if isinstance(default_transport, httpx.AsyncHTTPTransport):
                pool = default_transport._pool  # noqa: SLF001
                pool._network_backend = _PinnedBackend(  # noqa: SLF001
                    pool._network_backend,  # noqa: SLF001
                    self._pins,
                )
        else:
            self._client = httpx.AsyncClient(
                follow_redirects=False, timeout=timeout, transport=transport
            )

    async def __aenter__(self) -> SafeAsyncClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self._client.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def pins(self) -> dict[str, list[str]]:
        """Read-only view of the host→addresses pin map (for tests)."""
        return {host: list(addrs) for host, addrs in self._pins.items()}

    def _is_proxied(self, url: str) -> bool:
        """Return True if *url* would be routed via an httpx proxy mount."""
        transport = self._client._transport_for_url(httpx.URL(url))  # noqa: SLF001
        return transport is not self._client._transport  # noqa: SLF001

    async def _validate_and_pin(self, url: str) -> None:
        # Structural checks apply before each request. DNS resolution
        # and address pinning only run for direct destination
        # connections; proxy-mounted requests are passed to the
        # selected proxy.
        validate_structural(url)
        if self._is_proxied(url):
            return
        host, ips = await _hostname_for_pin_async(url)
        if ips:
            self._pins[host] = ips

    async def get(self, url: str) -> httpx.Response:
        """Issue a GET, revalidating every redirect target."""
        await self._validate_and_pin(url)
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            try:
                response = await self._client.get(current)
            except httpx.RemoteProtocolError as ex:
                # httpx eagerly parses the redirect Location header to
                # populate ``response.next_request`` — even with
                # follow_redirects=False — so a malformed value such as
                # ``http://[::1`` surfaces here as RemoteProtocolError
                # rather than at our manual ``join``. Translate to the
                # neutral rejection.
                raise ValueError(_REJECT_MESSAGE) from ex
            if not response.is_redirect:
                return response
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise ValueError(_REJECT_MESSAGE)
            current = _resolve_redirect(current, location)
            await self._validate_and_pin(current)
        raise ValueError(_REJECT_MESSAGE)

    @contextlib.asynccontextmanager
    async def stream(self, method: str, url: str) -> AsyncIterator[httpx.Response]:
        """Stream a response, revalidating every redirect target."""
        await self._validate_and_pin(url)
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            request = self._client.build_request(method, current)
            try:
                response = await self._client.send(request, stream=True)
            except httpx.RemoteProtocolError as ex:
                raise ValueError(_REJECT_MESSAGE) from ex
            if response.is_redirect:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise ValueError(_REJECT_MESSAGE)
                current = _resolve_redirect(current, location)
                await self._validate_and_pin(current)
                continue
            try:
                yield response
            finally:
                await response.aclose()
            return
        raise ValueError(_REJECT_MESSAGE)
