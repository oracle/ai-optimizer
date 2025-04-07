# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

output "client_repository" {
  description = "Path to push Client Image"
  value       = local.client_repository
}

output "server_repository" {
  description = "Path to push Client Image"
  value       = local.server_repository
}

output "kubeconfig_cmd" {
  description = "Command to generate kubeconfig file"
  value = format(
    "oci ce cluster create-kubeconfig --cluster-id %s --region %s --token-version 2.0.0 --kube-endpoint %s --file $HOME/.kube/config",
    oci_containerengine_cluster.default_cluster.id,
    var.region,
    oci_containerengine_cluster.default_cluster.endpoint_config[0].is_public_ip_enabled ? "PUBLIC_ENDPOINT" : "PRIVATE_ENDPOINT"
  )
}

// For Microservices Documentation
output "lb_compartment_ocid" {
  description = "LoadBalancer Compartment OCID"
  value       = oci_load_balancer.service_lb[0].compartment_id
}

output "lb_subnet_ocid" {
  description = "LoadBalancer Subnet OCID"
  value       = module.network.public_subnet_ocid
}

output "lb_ocid" {
  description = "LoadBalancer OCID"
  value       = oci_load_balancer.service_lb[0].id
}

output "lb_nsg_ocid" {
  description = "LoadBalancer NSG OCID(s)"
  value       = format("%s, %s", oci_core_network_security_group.service_lb_app_client[0].id, oci_core_network_security_group.service_lb_app_server[0].id)
}

output "lb_reserved_ip_ocid" {
  description = "LoadBalancer IP OCID(s)"
  value       = oci_core_public_ip.service_lb[0].id
}

output "lb_reserved_ip" {
  description = "LoadBalancer IP"
  value       = oci_core_public_ip.service_lb[0].ip_address
}

output "adb_ocid" {
  description = "ADB OCID"
  value       = oci_database_autonomous_database.default_adb.id
}

output "adb_service" {
  description = "ADB ServiceName"
  value       = format("%s_TP", oci_database_autonomous_database.default_adb.db_name)
}

output "adb_password" {
  description = "ADB ADMIN Password"
  value       = oci_database_autonomous_database.default_adb.admin_password
  sensitive = true
}