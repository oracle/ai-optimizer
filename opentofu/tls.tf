# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

// Self-signed CA
resource "tls_private_key" "ca" {
  count     = var.ssl_mode == "self-signed" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "tls_self_signed_cert" "ca" {
  count           = var.ssl_mode == "self-signed" ? 1 : 0
  private_key_pem = tls_private_key.ca[0].private_key_pem
  subject {
    common_name  = "AI Optimizer CA"
    organization = "Oracle"
  }
  validity_period_hours = 8760
  is_ca_certificate     = true
  allowed_uses          = ["cert_signing", "crl_signing"]
}

// Server certificate signed by the CA
resource "tls_private_key" "server" {
  count     = var.ssl_mode == "self-signed" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_cert_request" "server" {
  count           = var.ssl_mode == "self-signed" ? 1 : 0
  private_key_pem = tls_private_key.server[0].private_key_pem
  subject {
    common_name  = "AI Optimizer"
    organization = "Oracle"
  }
  dns_names    = var.ssl_hostname == "" ? [] : [lower(var.ssl_hostname)]
  ip_addresses = var.ssl_hostname == "" ? [oci_core_public_ip.lb.ip_address] : []
}

resource "tls_locally_signed_cert" "server" {
  count                 = var.ssl_mode == "self-signed" ? 1 : 0
  cert_request_pem      = tls_cert_request.server[0].cert_request_pem
  ca_private_key_pem    = tls_private_key.ca[0].private_key_pem
  ca_cert_pem           = tls_self_signed_cert.ca[0].cert_pem
  validity_period_hours = 8760
  allowed_uses          = ["digital_signature", "key_encipherment", "server_auth"]
}

resource "oci_certificates_management_certificate" "lb_cert" {
  provider              = oci-patched
  compartment_id        = local.compartment_ocid
  deletion_pending_days = 1

  name = format(
    "%s-lb-cert-%s",
    local.label_prefix,
    substr(sha256(oci_core_public_ip.lb.id), 0, 12),
  )

  certificate_config {
    config_type     = "IMPORTED"
    certificate_pem = local.ssl_cert_pem
    private_key_pem = local.ssl_key_pem
    cert_chain_pem  = local.ssl_ca_cert_pem

    version_name = format(
      "v-%s",
      substr(sha256(nonsensitive(local.ssl_cert_pem)), 0, 16),
    )
  }
}
