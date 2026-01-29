# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

locals {
  optimizer_values = templatefile("${path.module}/templates/ai-optimizer-values.yaml", {
    label                = var.label_prefix
    repository_base      = local.repository_base
    oci_region           = var.region
    db_type              = var.db_conn.db_type
    db_ocid              = var.db_ocid
    db_dsn               = var.db_conn.service
    db_name              = lower(var.db_name)
    node_pool_gpu_deploy = var.node_pool_gpu_deploy
    lb_ip                = var.lb.ip_address_details[0].ip_address
  })
}

resource "local_sensitive_file" "optimizer_values" {
  count           = var.deploy_optimizer ? 1 : 0
  content         = local.optimizer_values
  filename        = "${path.root}/cfgmgt/stage/ai-optimizer-values.yaml"
  file_permission = 0600
}