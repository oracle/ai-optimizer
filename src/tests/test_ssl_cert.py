"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for ssl_cert.py
"""
# spell-checker: disable

from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import NameOID

import ssl_cert


class TestGenerateSelfSignedCert:
    """Tests for generate_self_signed_cert."""

    def test_creates_cert_and_key_files(self, tmp_path):
        """generate_self_signed_cert should create both PEM files."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        ssl_cert.generate_self_signed_cert(cert_path, key_path)
        assert cert_path.exists()
        assert key_path.exists()

    def test_cert_is_valid_x509(self, tmp_path):
        """Generated certificate should be parseable X.509 with CN=localhost."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        ssl_cert.generate_self_signed_cert(cert_path, key_path)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == "localhost"

    def test_cert_has_san(self, tmp_path):
        """Generated certificate should include a SubjectAlternativeName for localhost."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        ssl_cert.generate_self_signed_cert(cert_path, key_path)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "localhost" in dns_names

    def test_key_is_rsa_2048(self, tmp_path):
        """Generated key should be an unencrypted RSA-2048 private key."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        ssl_cert.generate_self_signed_cert(cert_path, key_path)
        key = load_pem_private_key(key_path.read_bytes(), password=None)
        assert isinstance(key, RSAPrivateKey)
        assert key.key_size == 2048

    def test_key_file_permissions(self, tmp_path):
        """Generated key file should have restrictive permissions (0o600)."""
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        ssl_cert.generate_self_signed_cert(cert_path, key_path)
        mode = key_path.stat().st_mode & 0o777
        assert mode == 0o600


class TestResolveOrGenerateCert:
    """Tests for resolve_or_generate_cert (the shared resolution core)."""

    def test_uses_provided_paths_without_generating(self, tmp_path):
        """When both paths are provided, return them and do not generate."""
        cert = tmp_path / "configured.crt"
        key = tmp_path / "configured.key"
        with patch.object(ssl_cert, "generate_self_signed_cert") as mock_gen:
            result = ssl_cert.resolve_or_generate_cert(str(cert), str(key), tmp_path / "src")
        mock_gen.assert_not_called()
        assert result == (cert, key)

    def test_generates_when_both_missing(self, tmp_path):
        """Empty strings should auto-generate under <script_dir>/../tmp/ssl."""
        script_dir = tmp_path / "src"
        script_dir.mkdir()
        cert, key = ssl_cert.resolve_or_generate_cert("", "", script_dir)
        assert cert.exists()
        assert key.exists()
        assert cert.name == "cert.pem"
        assert key.name == "key.pem"

    def test_generates_when_only_one_provided(self, tmp_path):
        """A single provided path is insufficient; fall back to generation."""
        script_dir = tmp_path / "src"
        script_dir.mkdir()
        cert, key = ssl_cert.resolve_or_generate_cert(str(tmp_path / "only.crt"), "", script_dir)
        assert cert.name == "cert.pem"
        assert cert.exists()

    def test_skips_when_existing(self, tmp_path):
        """Existing generated files should be reused, not regenerated."""
        script_dir = tmp_path / "src"
        script_dir.mkdir()
        ssl_dir = tmp_path / "tmp" / "ssl"
        ssl_dir.mkdir(parents=True)
        (ssl_dir / "cert.pem").write_text("existing-cert")
        (ssl_dir / "key.pem").write_text("existing-key")
        cert, key = ssl_cert.resolve_or_generate_cert("", "", script_dir)
        assert cert.read_text(encoding="utf-8") == "existing-cert"
        assert key.read_text(encoding="utf-8") == "existing-key"

    def test_creates_ssl_directory(self, tmp_path):
        """The ssl directory should be created when it does not exist."""
        script_dir = tmp_path / "deep" / "nested" / "src"
        script_dir.mkdir(parents=True)
        ssl_cert.resolve_or_generate_cert("", "", script_dir)
        assert (script_dir.parent / "tmp" / "ssl").is_dir()


class TestEnsureSslCert:
    """Tests for the ensure_ssl_cert environment-variable wrapper."""

    def test_generates_when_env_missing(self, tmp_path, monkeypatch):
        """ensure_ssl_cert should generate files when env vars are empty."""
        monkeypatch.delenv("TEST_CERT", raising=False)
        monkeypatch.delenv("TEST_KEY", raising=False)
        script_dir = tmp_path / "src"
        script_dir.mkdir()
        cert, key = ssl_cert.ensure_ssl_cert(script_dir, "TEST_CERT", "TEST_KEY")
        assert cert.exists()
        assert key.exists()
        assert cert.name == "cert.pem"
        assert key.name == "key.pem"

    def test_uses_env_var_paths(self, tmp_path, monkeypatch):
        """ensure_ssl_cert should use env var paths when both are set."""
        cert_path = tmp_path / "my_cert.pem"
        key_path = tmp_path / "my_key.pem"
        cert_path.write_text("cert-content")
        key_path.write_text("key-content")
        monkeypatch.setenv("TEST_CERT", str(cert_path))
        monkeypatch.setenv("TEST_KEY", str(key_path))
        cert, key = ssl_cert.ensure_ssl_cert(tmp_path, "TEST_CERT", "TEST_KEY")
        assert cert == cert_path
        assert key == key_path
