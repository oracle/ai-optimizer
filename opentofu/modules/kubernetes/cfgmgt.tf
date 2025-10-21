# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

locals {
  k8s_manifest = templatefile("${path.module}/templates/k8s_manifest.yaml", {
    label                       = var.label_prefix
    repository_host             = local.repository_host
    optimizer_repository_server = local.optimizer_repository_server
    optimizer_repository_client = local.optimizer_repository_client
    compartment_ocid            = var.lb.compartment_id
    lb_ocid                     = var.lb.id
    lb_subnet_ocid              = var.public_subnet_id
    lb_ip_ocid                  = var.lb.ip_address_details[0].ip_address
    lb_nsgs                     = var.lb_nsg_id
    lb_min_shape                = var.lb.shape_details[0].minimum_bandwidth_in_mbps
    lb_max_shape                = var.lb.shape_details[0].maximum_bandwidth_in_mbps
    db_name                     = lower(var.db_name)
    db_username                 = var.db_conn.username
    db_password                 = var.db_conn.password
    db_service                  = var.db_conn.service
    optimizer_api_key           = random_string.optimizer_api_key.result
    deploy_buildkit             = var.byo_ocir_url == ""
    deploy_optimizer            = var.deploy_optimizer
    optimizer_version           = var.optimizer_version
  })

  helm_values = templatefile("${path.module}/templates/optimizer_helm_values.yaml", {
    label                       = var.label_prefix
    optimizer_repository_server = local.optimizer_repository_server
    optimizer_repository_client = local.optimizer_repository_client
    oci_tenancy                 = var.tenancy_id
    oci_region                  = var.region
    db_type                     = var.db_conn.db_type
    db_ocid                     = var.db_ocid
    db_dsn                      = var.db_conn.service
    db_name                     = lower(var.db_name)
    node_pool_gpu_deploy        = var.node_pool_gpu_deploy
    lb_ip                       = var.lb.ip_address_details[0].ip_address
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

resource "local_sensitive_file" "optimizer_helm_values" {
  count           = var.deploy_optimizer ? 1 : 0
  content         = local.helm_values
  filename        = "${path.root}/cfgmgt/stage/optimizer-helm-values.yaml"
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
      python3 ${path.root}/cfgmgt/apply.py ${var.label_prefix} ${var.label_prefix} --private_endpoint ${local.orm_pe}
    EOT
  }
  depends_on = [
    local_sensitive_file.kubeconfig,
    local_sensitive_file.k8s_manifest,
    local_sensitive_file.optimizer_helm_values,
    oci_containerengine_node_pool.cpu_node_pool_details,
    oci_containerengine_node_pool.gpu_node_pool_details,
    oci_containerengine_addon.oraoper_addon,
    oci_containerengine_addon.certmgr_addon,
    oci_containerengine_addon.ingress_addon
  ]
}