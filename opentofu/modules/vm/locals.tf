# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

locals {
  streamlit_client_port      = 8501
  fastapi_server_port        = 8000
  lb_idle_timeout_in_seconds = 1800
}

locals {
  cloud_init_compute = templatefile("${path.module}/templates/cloudinit-compute.tpl", {
    compartment_id         = var.compartment_id
    db_type                = var.db_conn.db_type
    db_password            = var.db_conn.password
    db_service             = var.db_conn.service
    optimizer_version      = var.optimizer_version
    optimizer_branch       = var.optimizer_branch
    app_version            = var.app_version
    install_ollama         = var.vm_is_gpu_shape || var.compute_install_ollama
    object_storage_bucket  = var.object_storage_bucket
    client_cookie_secret   = var.client_cookie_secret
    oidc_issuer            = var.oidc_issuer
    oidc_audience          = var.oidc_audience
    oidc_required_scopes   = jsonencode(tolist(var.oidc_required_scopes))
    oidc_client_id         = var.oidc_client_id
    oidc_client_secret     = var.oidc_client_secret
    oidc_redirect_uri      = var.oidc_redirect_uri
    oidc_admin_subject     = var.oidc_admin_subject
    oidc_public_server_url = var.oidc_public_server_url
  })

  cloud_init_database = templatefile("${path.module}/templates/cloudinit-database.tpl", {
    compartment_id = var.compartment_id
    db_name        = var.db_name
    db_type        = var.db_conn.db_type
    db_dba_user    = var.db_conn.username
    db_password    = var.db_conn.password
    db_service     = var.db_conn.service
  })

  vm_compute_shape = var.vm_is_gpu_shape ? var.compute_gpu_shape : var.compute_cpu_shape
}
