# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

output "app_version" {
  description = "Application Version"
  value       = local.app_version
}

output "app_name" {
  description = "Application Name (Label).  The namespace for K8s installations"
  value       = local.label_prefix
}

output "optimizer_client_url" {
  description = "URL for AI Optimizer and Toolkit Client Access"
  value = var.deploy_optimizer ? format(
    "%s://%s", local.ssl_enabled ? "https" : "http",
    oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address
  ) : "N/A"
}

output "optimizer_server_url" {
  description = "URL for AI Optimizer and Toolkit Server API Access"
  value = var.deploy_optimizer ? format(
    "%s://%s:%d/v1/docs", local.ssl_enabled ? "https" : "http",
    oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address,
    local.ssl_enabled ? local.lb_server_https_port : local.lb_server_http_port,
  ) : "N/A"
}

output "ssl_ca_certificate" {
  description = "CA certificate PEM (self-signed mode only — add to trust store to avoid browser warnings)"
  value       = var.ssl_mode == "self-signed" ? local.ssl_ca_cert_pem : "N/A"
  sensitive   = true
}
