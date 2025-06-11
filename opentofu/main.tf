# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// random
resource "random_pet" "label" {
  length = 1
}

resource "random_password" "adb_char" {
  length  = 2
  special = false
  numeric = false
}

resource "random_password" "adb_rest" {
  length           = 14
  min_numeric      = 2
  min_lower        = 2
  min_upper        = 2
  min_special      = 2
  override_special = "!$%^*-_"
  keepers = {
    uuid = "uuid()"
  }
}



// Network
module "network" {
  source         = "./modules/network"
  compartment_id = local.compartment_ocid
  label_prefix   = local.label_prefix
  infra          = var.infrastructure
}

// Load Balancer
resource "oci_load_balancer_load_balancer" "lb" {
  compartment_id = local.compartment_ocid
  display_name   = format("%s-lb", local.label_prefix)
  shape          = "flexible"
  is_private     = false
  shape_details {
    minimum_bandwidth_in_mbps = var.lb_min_shape
    maximum_bandwidth_in_mbps = var.lb_max_shape
  }
  subnet_ids = [
    module.network.public_subnet_ocid
  ]
  network_security_group_ids = [
    oci_core_network_security_group.lb.id,
  ]
}

// Autonomous Database
resource "oci_database_autonomous_database" "default_adb" {
  admin_password                       = local.adb_password
  autonomous_maintenance_schedule_type = "REGULAR"
  character_set                        = "AL32UTF8"
  compartment_id                       = local.compartment_ocid
  compute_count                        = var.adb_ecpu_core_count
  compute_model                        = "ECPU"
  data_storage_size_in_gb              = var.adb_data_storage_size_in_gb
  database_edition                     = var.adb_license_model == "BRING_YOUR_OWN_LICENSE" ? var.adb_edition : null
  db_name                              = local.adb_name
  db_version                           = var.adb_version
  db_workload                          = "OLTP"
  display_name                         = local.adb_name
  is_free_tier                         = false
  is_auto_scaling_enabled              = var.adb_is_cpu_auto_scaling_enabled
  is_auto_scaling_for_storage_enabled  = var.adb_is_storage_auto_scaling_enabled
  is_dedicated                         = false
  license_model                        = var.adb_license_model
  is_mtls_connection_required          = true
  whitelisted_ips                      = local.adb_whitelist_cidrs
}

// Virtual Machine
module "vm" {
  count                 = var.infrastructure == "VM" ? 1 : 0
  source                = "./modules/vm"
  label_prefix          = local.label_prefix
  tenancy_id            = var.tenancy_ocid
  compartment_id        = local.compartment_ocid
  vcn_id                = module.network.vcn_ocid
  lb_id                 = oci_load_balancer_load_balancer.lb.id
  lb_client_port        = local.lb_client_port
  lb_server_port        = local.lb_server_port
  region                = var.region
  adb_name              = local.adb_name
  adb_password          = local.adb_password
  streamlit_client_port = local.streamlit_client_port
  fastapi_server_port   = local.fastapi_server_port
  compute_os_ver        = var.compute_os_ver
  compute_cpu_ocpu      = var.compute_cpu_ocpu
  compute_cpu_shape     = var.compute_cpu_shape
  availability_domains  = local.availability_domains
  private_subnet_id     = module.network.private_subnet_ocid
  providers = {
    oci.home_region = oci.home_region
  }
}

// Kubernetes
module "kubernetes" {
  count                          = var.infrastructure == "Kubernetes" ? 1 : 0
  source                         = "./modules/kubernetes"
  label_prefix                   = local.label_prefix
  tenancy_id                     = var.tenancy_ocid
  compartment_id                 = local.compartment_ocid
  vcn_id                         = module.network.vcn_ocid
  region                         = var.region
  lb                             = oci_load_balancer_load_balancer.lb
  adb_id                         = oci_database_autonomous_database.default_adb.id
  adb_name                       = local.adb_name
  adb_password                   = local.adb_password
  k8s_api_is_public              = var.k8s_api_is_public
  k8s_node_pool_gpu_deploy       = var.k8s_node_pool_gpu_deploy
  k8s_gpu_node_pool_size         = var.k8s_gpu_node_pool_size
  k8s_version                    = var.k8s_version
  k8s_cpu_node_pool_size         = var.k8s_cpu_node_pool_size
  k8s_api_endpoint_allowed_cidrs = var.k8s_api_endpoint_allowed_cidrs
  compute_os_ver                 = var.compute_os_ver
  compute_cpu_ocpu               = var.compute_cpu_ocpu
  compute_gpu_shape              = var.compute_gpu_shape
  compute_cpu_shape              = var.compute_cpu_shape
  availability_domains           = local.availability_domains
  public_subnet_id               = module.network.public_subnet_ocid
  private_subnet_id              = module.network.private_subnet_ocid
  lb_nsg_id                      = oci_core_network_security_group.lb.id
  providers = {
    oci.home_region = oci.home_region
  }
}