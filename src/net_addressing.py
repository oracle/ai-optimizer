"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared address/URL helpers for the API Server bind/connect distinction.

A bind address (what uvicorn listens on) is not always a usable client target:
wildcard binds such as ``0.0.0.0`` / ``::`` accept connections but cannot be
dialed. These helpers translate bind addresses into connectable hosts, build
IPv6-aware netloc strings, decide when the configured service port belongs in a
URL, and select TLS verification for loopback self-signed certificates.

It lives at the top level so both the client and server trees can import it
(mirrors ``url_safety``); neither tree is guaranteed to be present at runtime.
"""

from urllib.parse import urlparse

# Wildcard bind addresses mapped to the loopback host used to reach them.
WILDCARD_TO_LOOPBACK = {
    "0.0.0.0": "127.0.0.1",
    "::": "::1",
    "0:0:0:0:0:0:0:0": "::1",
}
# Wildcard bind hosts (listen-on-all); usable for binding, not for connecting.
WILDCARD_HOSTS = frozenset(WILDCARD_TO_LOOPBACK)
# Every host that denotes the local machine: loopback plus wildcard binds.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"}) | WILDCARD_HOSTS
# In-cluster Kubernetes service DNS suffixes that resolve to the app server.
K8S_SERVICE_SUFFIXES = (".svc", ".svc.cluster.local")


def connect_host(host: str | None) -> str:
    """Return a dialable host for a bind/configured host.

    Wildcard bind addresses are useful for listening, but they are not stable
    client targets. Convert only those wildcard values to loopback; leave DNS
    names and concrete IPs untouched so normal resolver behavior applies.
    """
    raw = (host or "").strip()
    normalized = raw.strip("[]").casefold()
    return WILDCARD_TO_LOOPBACK.get(normalized, raw or "127.0.0.1")


def netloc(host: str, port: int | None) -> str:
    """Build a ``host[:port]`` netloc, bracketing bare IPv6 literals."""
    bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{bracketed}:{port}" if port else bracketed


def should_inject_server_port(parsed_hostname: str | None, connect_target: str) -> bool:
    """Return True when the configured service port should be part of the URL.

    External URLs without an explicit port should keep their scheme default
    (e.g. HTTPS -> 443). Local/all-in-one URLs and Kubernetes service DNS
    names use the app server's configured service port.
    """
    host = (parsed_hostname or connect_target).strip("[]").casefold()
    return host in LOCAL_HOSTS or host.endswith(K8S_SERVICE_SUFFIXES)


def verify_for_url(url: str) -> bool:
    """Return whether httpx should verify TLS certificates for *url*.

    The all-in-one local server can run with an auto-generated self-signed
    certificate. Disable verification only for loopback HTTPS targets; keep
    normal certificate verification for every external HTTPS endpoint.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return True
    host = (parsed.hostname or "").strip("[]").casefold()
    return host not in LOCAL_HOSTS
