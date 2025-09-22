# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

locals {
  cloud_init_compute = templatefile("${path.module}/templates/cloudinit-compute.tpl", {
    tenancy_id            = var.tenancy_id
    compartment_id        = var.compartment_id
    oci_region            = var.region
    db_name               = var.adb_name
    db_password           = var.adb_password
    optimizer_version     = var.optimizer_version
    optimizer_client_port = var.streamlit_client_port
    optimizer_server_port = var.fastapi_server_port
    install_ollama        = var.vm_is_gpu_shape ? true : false
  })

  cloud_init_database = templatefile("${path.module}/templates/cloudinit-database.tpl", {
    tenancy_id     = var.tenancy_id
    compartment_id = var.compartment_id
    oci_region     = var.region
    db_name        = var.adb_name
    db_password    = var.adb_password
    install_ollama = var.vm_is_gpu_shape ? true : false
  })

  vm_compute_shape = var.vm_is_gpu_shape ? var.compute_gpu_shape : var.compute_cpu_shape
}