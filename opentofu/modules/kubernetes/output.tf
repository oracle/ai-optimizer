# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

output "kubeconfig_cmd" {
  description = "Command to generate kubeconfig file"
  value = format(
    "oci ce cluster create-kubeconfig --cluster-id %s --region %s --token-version 2.0.0 --kube-endpoint %s --file $HOME/.kube/config --with-auth-context --profile DEFAULT",
    oci_containerengine_cluster.default_cluster.id,
    var.region,
    oci_containerengine_cluster.default_cluster.endpoint_config[0].is_public_ip_enabled ? "PUBLIC_ENDPOINT" : "PRIVATE_ENDPOINT"
  )
}

output "helm_manual_instructions" {
  description = "Instructions for manual Helm deployment (when cfgmgt was skipped)"
  value       = local.should_show_manual_steps ? local.manual_helm_instructions : null
}