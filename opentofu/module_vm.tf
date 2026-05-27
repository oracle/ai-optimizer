# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

variable "vm_is_gpu_shape" {
  type    = bool
  default = false
}

variable "compute_install_ollama" {
  type    = bool
  default = false
}

# Blocking guard for AlwaysFree compute sizing. check {} blocks only warn,
# so we use a precondition that fails plan/apply when violated.
resource "terraform_data" "always_free_validation" {
  count = local.is_always_free ? 1 : 0

  lifecycle {
    precondition {
      condition     = var.compute_cpu_ocpu >= 1 && var.compute_cpu_ocpu <= 4
      error_message = "AlwaysFree requires compute_cpu_ocpu between 1 and 4 (A1.Flex shape is forced automatically)."
    }
  }
}

module "vm" {
  for_each               = contains(["VM", "AlwaysFree"], var.infrastructure) ? { managed = true } : {}
  source                 = "./modules/vm"
  optimizer_version      = var.optimizer_version
  optimizer_branch       = local.optimizer_branch
  app_version            = local.app_version #Triggers Upgrades
  label_prefix           = local.label_prefix
  tenancy_id             = var.tenancy_ocid
  compartment_id         = local.compartment_ocid
  vcn_id                 = local.vcn_ocid
  oci_services           = data.oci_core_services.core_services.services.0
  lb_id                  = oci_load_balancer_load_balancer.lb.id
  lb_client_http_port    = local.lb_client_http_port
  lb_client_https_port   = local.lb_client_https_port
  lb_server_http_port    = local.lb_server_http_port
  lb_server_https_port   = local.lb_server_https_port
  ssl_enabled            = local.ssl_enabled
  ssl_cert_pem           = local.ssl_cert_pem
  ssl_key_pem            = local.ssl_key_pem
  ssl_ca_cert            = local.ssl_ca_cert_pem
  db_name                = local.db_name
  db_conn                = local.db_conn
  vm_is_gpu_shape        = local.is_always_free ? false : var.vm_is_gpu_shape
  compute_install_ollama = var.compute_install_ollama
  compute_os_ver         = local.compute_os_ver
  compute_cpu_ocpu       = var.compute_cpu_ocpu
  compute_cpu_memory_gbs = local.compute_cpu_memory_gbs
  compute_cpu_shape      = local.compute_cpu_shape
  compute_gpu_shape      = var.compute_gpu_shape
  availability_domains   = local.availability_domains
  private_subnet_id      = local.private_subnet_ocid
  object_storage_bucket  = local.object_storage_bucket
  client_cookie_secret   = random_password.client_cookie.result
  providers = {
    oci.home_region = oci.home_region
  }
}