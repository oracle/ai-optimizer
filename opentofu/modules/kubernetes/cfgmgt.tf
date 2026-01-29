# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

locals {
  k8s_manifest = templatefile("${path.module}/templates/k8s-manifest.yaml", {
    label             = var.label_prefix
    repository_host   = local.repository_host
    repository_base   = local.repository_base
    compartment_ocid  = var.lb.compartment_id
    lb_ocid           = var.lb.id
    lb_subnet_ocid    = var.public_subnet_id
    lb_ip_ocid        = var.lb.ip_address_details[0].ip_address
    lb_nsgs           = var.lb_nsg_id
    lb_min_shape      = var.lb.shape_details[0].minimum_bandwidth_in_mbps
    lb_max_shape      = var.lb.shape_details[0].maximum_bandwidth_in_mbps
    db_name           = lower(var.db_name)
    db_username       = var.db_conn.username
    db_password       = var.db_conn.password
    db_service        = var.db_conn.service
    optimizer_api_key = random_string.optimizer_api_key.result
    deploy_buildkit   = var.byo_ocir_url == ""
    deploy_optimizer  = var.deploy_optimizer
    optimizer_version = var.optimizer_version
  })
}

resource "local_sensitive_file" "kubeconfig" {
  content         = data.oci_containerengine_cluster_kube_config.default_cluster_kube_config.content
  filename        = "${path.root}/cfgmgt/stage/kubeconfig"
  file_permission = 0600
}

resource "local_sensitive_file" "k8s_manifest" {
  content         = local.k8s_manifest
  filename        = "${path.root}/cfgmgt/stage/k8s-manifest.yaml"
  file_permission = 0600
}

resource "null_resource" "apply" {
  count = var.run_cfgmgt ? 1 : 0
  triggers = {
    always_run = "${timestamp()}"
  }

  lifecycle {
    precondition {
      condition     = local.can_apply_cfgmgt
      error_message = local.cfgmgt_error_message
    }
  }

  provisioner "local-exec" {
    command = <<EOT
      python3 ${path.root}/cfgmgt/apply.py ${var.label_prefix}${local.orm_pe != "" ? " --private_endpoint ${local.orm_pe}" : ""} --optimizer_version ${var.optimizer_version}
    EOT
  }
  depends_on = [
    local_sensitive_file.kubeconfig,
    local_sensitive_file.k8s_manifest,
    local_sensitive_file.optimizer_values,
    oci_containerengine_node_pool.cpu_node_pool_details,
    oci_containerengine_node_pool.gpu_node_pool_details,
    oci_containerengine_addon.oraoper_addon,
    oci_containerengine_addon.certmgr_addon,
    oci_containerengine_addon.ingress_addon
  ]
}