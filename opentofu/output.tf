# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

output "app_version" {
  description = "Oracle AI Optimizer and Toolkit Version"
  value       = local.app_version
}

output "client_url" {
  description = "URL for Client Access"
  value       = format("http://%s", oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address)
}

output "server_url" {
  description = "URL for Client Access"
  value       = format("http://%s:8000/v1/docs", oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address)
}

output "kubeconfig_cmd" {
  description = "Command to generate kubeconfig file"
  value       = var.infrastructure == "Kubernetes" ? module.kubernetes["managed"].kubeconfig_cmd : "N/A"
}