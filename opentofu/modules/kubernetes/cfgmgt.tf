# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

locals {
  helm_values = templatefile("${path.module}/templates/helm_values.yaml", {
    label                    = var.label_prefix
    repository_server        = local.repository_server
    repository_client        = local.repository_client
    oci_tenancy              = var.tenancy_id
    oci_region               = var.region
    adb_ocid                 = var.adb_id
    adb_name                 = lower(var.adb_name)
    k8s_node_pool_gpu_deploy = var.k8s_node_pool_gpu_deploy
    lb_ip                    = var.lb.ip_address_details[0].ip_address
  })

  k8s_manifest = templatefile("${path.module}/templates/k8s_manifest.yaml", {
    label             = var.label_prefix
    repository_host   = local.repository_host
    repository_server = local.repository_server
    repository_client = local.repository_client
    compartment_ocid  = var.lb.compartment_id
    lb_ocid           = var.lb.id
    lb_subnet_ocid    = var.public_subnet_id
    lb_ip_ocid        = var.lb.ip_address_details[0].ip_address
    lb_nsgs           = var.lb_nsg_id
    lb_min_shape      = var.lb.shape_details[0].minimum_bandwidth_in_mbps
    lb_max_shape      = var.lb.shape_details[0].maximum_bandwidth_in_mbps
    adb_name          = lower(var.adb_name)
    adb_password      = var.adb_password
    adb_service       = format("%s_TP", var.adb_name)
    api_key           = random_string.api_key.result
  })
}

resource "local_sensitive_file" "kubeconfig" {
  content         = data.oci_containerengine_cluster_kube_config.default_cluster_kube_config.content
  filename        = "${path.root}/cfgmgt/stage/kubeconfig"
  file_permission = 0600
}

resource "local_sensitive_file" "helm_values" {
  content         = local.helm_values
  filename        = "${path.root}/cfgmgt/stage/helm-values.yaml"
  file_permission = 0600
}

resource "local_sensitive_file" "k8s_manifest" {
  content         = local.k8s_manifest
  filename        = "${path.root}/cfgmgt/stage/k8s-manifest.yaml"
  file_permission = 0600
}

resource "null_resource" "apply" {
  triggers = {
    always_run = "${timestamp()}"
  }
  provisioner "local-exec" {
    command = <<EOT
      python3 ${path.root}/cfgmgt/apply.py ${var.label_prefix} ${var.label_prefix}
    EOT
  }
  depends_on = [
    local_sensitive_file.kubeconfig,
    local_sensitive_file.helm_values,
    local_sensitive_file.k8s_manifest,
    oci_containerengine_node_pool.default_node_pool_details,
    oci_containerengine_node_pool.gpu_node_pool_details
  ]
}