# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

resource "tls_private_key" "acme_ca" {
  algorithm = "RSA"
  rsa_bits  = "4096"
}

resource "tls_self_signed_cert" "acme_ca" {
  private_key_pem   = tls_private_key.acme_ca.private_key_pem
  is_ca_certificate = true

  subject {
    common_name         = "Acme Self Signed CA"
    organization        = "Acme Self Signed"
    organizational_unit = "acme"
  }

  validity_period_hours = 87659

  allowed_uses = [
    "digital_signature",
    "cert_signing",
    "crl_signing",
  ]
}

resource "tls_private_key" "example_com" {
  algorithm = "RSA"
  rsa_bits  = "4096"
}

resource "tls_cert_request" "example_com" {
  private_key_pem = tls_private_key.example_com.private_key_pem

  dns_names = ["example.com"]

  subject {
    common_name         = "example.com"
    organization        = "Example Self Signed"
    country             = "GB"
    organizational_unit = "example.com"
  }
}

resource "tls_locally_signed_cert" "example_com" {
  cert_request_pem   = tls_cert_request.example_com.cert_request_pem
  ca_private_key_pem = tls_private_key.acme_ca.private_key_pem
  ca_cert_pem        = tls_self_signed_cert.acme_ca.cert_pem

  validity_period_hours = 87659

  allowed_uses = [
    "digital_signature",
    "key_encipherment",
    "server_auth",
    "client_auth",
  ]
}