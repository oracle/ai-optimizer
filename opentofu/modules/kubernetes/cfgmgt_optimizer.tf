# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

locals {
  # BYO OCIR contract: every image must come from the BYO registry. The
  # SigNoz subchart deploys a multi-image stack (clickhouse, otel-collector,
  # query-service, frontend, alertmanager, schema-migrator) from upstream
  # registries with no chart-side override path here, so enabling SigNoz
  # under BYO would silently bypass the constraint. Force-disable in BYO
  # installs; operators wanting observability with BYO must mirror those
  # images and override values out of band.
  signoz_enabled = var.is_observability_enabled && var.byo_ocir_url == ""

  optimizer_values = templatefile("${path.module}/templates/ai-optimizer-values.yaml", {
    label                    = var.label_prefix
    repository_base          = local.repository_base
    oci_region               = var.region
    db_type                  = var.db_conn.db_type
    db_ocid                  = var.db_ocid
    db_dsn                   = var.db_conn.service
    db_name                  = lower(var.db_name)
    node_pool_gpu_deploy     = var.node_pool_gpu_deploy
    ssl_enabled              = var.ssl_enabled
    client_cookie_secret     = var.client_cookie_secret
    is_observability_enabled = var.is_observability_enabled
    signoz_enabled           = local.signoz_enabled
  })
}

resource "local_sensitive_file" "optimizer_values" {
  count           = var.deploy_optimizer ? 1 : 0
  content         = local.optimizer_values
  filename        = "${path.root}/cfgmgt/stage/ai-optimizer-values.yaml"
  file_permission = 0600
}