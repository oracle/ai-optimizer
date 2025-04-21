# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

output "client_url" {
  description = "URL for Client Access"
  value       = format("http://%s", oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address)
}

output "server_url" {
  description = "URL for Client Access"
  value       = format("http://%s:8000/v1/docs", oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address)
}

output "client_repository" {
  description = "Path to push Client Image"
  value       = var.infrastructure == "Kubernetes" ? module.kubernetes[0].client_repository : "N/A"
}

output "server_repository" {
  description = "Path to push Client Image"
  value       = var.infrastructure == "Kubernetes" ? module.kubernetes[0].server_repository : "N/A"
}

output "kubeconfig_cmd" {
  description = "Command to generate kubeconfig file"
  value       = var.infrastructure == "Kubernetes" ? module.kubernetes[0].kubeconfig_cmd : "N/A"
}

output "k8s_manifest" {
  description = "Kubernetes Manifest"
  value       = var.infrastructure == "Kubernetes" ? module.kubernetes[0].k8s_manifest : "N/A"
  sensitive   = true
}

output "helm_values" {
  description = "Helm Values"
  value       = var.infrastructure == "Kubernetes" ? module.kubernetes[0].helm_values : "N/A"
  sensitive   = true
}