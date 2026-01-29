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
  value       = var.deploy_optimizer ? format("http://%s", oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address) : "N/A"
}

output "optimizer_server_url" {
  description = "URL for AI Optimizer and Toolkit Server API Access"
  value       = var.deploy_optimizer ? format("http://%s:8000/v1/docs", oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address) : "N/A"
}
