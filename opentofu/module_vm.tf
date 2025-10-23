# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

variable "vm_is_gpu_shape" {
  type    = bool
  default = false
}

module "vm" {
  for_each             = var.infrastructure == "VM" ? { managed = true } : {}
  source               = "./modules/vm"
  optimizer_version    = var.optimizer_version
  label_prefix         = local.label_prefix
  tenancy_id           = var.tenancy_ocid
  compartment_id       = local.compartment_ocid
  vcn_id               = local.vcn_ocid
  oci_services         = data.oci_core_services.core_services.services.0
  lb_id                = oci_load_balancer_load_balancer.lb.id
  lb_client_port       = local.lb_client_port
  lb_server_port       = local.lb_server_port
  db_name              = local.db_name
  db_conn              = local.db_conn
  vm_is_gpu_shape      = var.vm_is_gpu_shape
  compute_os_ver       = local.compute_os_ver
  compute_cpu_ocpu     = var.compute_cpu_ocpu
  compute_cpu_shape    = var.compute_cpu_shape
  compute_gpu_shape    = var.compute_gpu_shape
  availability_domains = local.availability_domains
  private_subnet_id    = local.private_subnet_ocid
  providers = {
    oci.home_region = oci.home_region
  }
}