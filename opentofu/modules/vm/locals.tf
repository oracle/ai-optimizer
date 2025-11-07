# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

locals {
  streamlit_client_port = 8501
  fastapi_server_port   = 8000
}

locals {
  cloud_init_compute = templatefile("${path.module}/templates/cloudinit-compute.tpl", {
    db_type           = var.db_conn.db_type
    db_password       = var.db_conn.password
    db_service        = var.db_conn.service
    optimizer_version = var.optimizer_version
    install_ollama    = var.vm_is_gpu_shape ? true : false
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