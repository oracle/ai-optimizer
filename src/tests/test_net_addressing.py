"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Canonical tests for the shared bind/connect address helpers.
"""

from net_addressing import connect_host, netloc, should_inject_server_port, verify_for_url


class TestConnectHost:
    """Wildcard bind addresses become dialable loopback targets; others pass through."""

    def test_wildcard_ipv4_becomes_loopback(self):
        assert connect_host("0.0.0.0") == "127.0.0.1"

    def test_wildcard_ipv6_becomes_loopback(self):
        assert connect_host("::") == "::1"
        assert connect_host("0:0:0:0:0:0:0:0") == "::1"
        assert connect_host("[::]") == "::1"

    def test_concrete_and_dns_hosts_pass_through(self):
        assert connect_host("127.0.0.1") == "127.0.0.1"
        assert connect_host("10.1.2.3") == "10.1.2.3"
        assert connect_host("api.example.com") == "api.example.com"

    def test_empty_or_none_defaults_to_loopback(self):
        assert connect_host(None) == "127.0.0.1"
        assert connect_host("") == "127.0.0.1"
        assert connect_host("   ") == "127.0.0.1"


class TestNetloc:
    """host[:port] construction brackets bare IPv6 literals exactly once."""

    def test_ipv4_with_and_without_port(self):
        assert netloc("127.0.0.1", 8000) == "127.0.0.1:8000"
        assert netloc("127.0.0.1", None) == "127.0.0.1"

    def test_bare_ipv6_is_bracketed(self):
        assert netloc("::1", 9000) == "[::1]:9000"
        assert netloc("::1", None) == "[::1]"

    def test_already_bracketed_ipv6_not_double_bracketed(self):
        assert netloc("[::1]", 9000) == "[::1]:9000"

    def test_dns_host(self):
        assert netloc("api.example.com", 443) == "api.example.com:443"


class TestShouldInjectServerPort:
    """Local/all-in-one and Kubernetes service hosts use the configured port."""

    def test_local_hosts_inject(self):
        assert should_inject_server_port("127.0.0.1", "127.0.0.1") is True
        assert should_inject_server_port("localhost", "localhost") is True
        assert should_inject_server_port("0.0.0.0", "127.0.0.1") is True

    def test_kubernetes_service_hosts_inject(self):
        assert should_inject_server_port("optimizer-server.default.svc", "optimizer-server.default.svc") is True
        assert should_inject_server_port("svc.default.svc.cluster.local", "svc.default.svc.cluster.local") is True

    def test_external_hosts_do_not_inject(self):
        external = "release-ai.appoci.oraclecorp.com"
        assert should_inject_server_port(external, external) is False

    def test_missing_hostname_falls_back_to_connect_target(self):
        assert should_inject_server_port(None, "127.0.0.1") is True
        assert should_inject_server_port(None, "api.example.com") is False


class TestVerifyForUrl:
    """TLS verification is dropped only for loopback HTTPS (self-signed local cert)."""

    def test_local_https_disables_verification(self):
        assert verify_for_url("https://127.0.0.1:8000/v1") is False
        assert verify_for_url("https://localhost:8000/v1") is False
        assert verify_for_url("https://[::1]:8000/v1") is False
        assert verify_for_url("https://0.0.0.0:8000/mcp/") is False

    def test_external_https_keeps_verification(self):
        assert verify_for_url("https://release-ai.appoci.oraclecorp.com/v1") is True

    def test_http_keeps_default_verification_flag(self):
        assert verify_for_url("http://127.0.0.1:8000/v1") is True
