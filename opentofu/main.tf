# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

// random
resource "random_pet" "label" {
  length = 1
}

resource "random_password" "adb_char" {
  count   = var.byo_db_password == "" ? 1 : 0
  length  = 2
  special = false
  numeric = false
}

resource "random_password" "adb_rest" {
  count            = var.byo_db_password == "" ? 1 : 0
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

// Cookie Secret
resource "random_password" "client_cookie" {
  length  = 48
  special = false
  keepers = {
    uuid = "uuid()"
  }
}

// Load Balancer
resource "oci_load_balancer_load_balancer" "lb" {
  compartment_id = local.compartment_ocid
  display_name   = format("%s-lb", local.label_prefix)
  shape          = "flexible"
  is_private     = false
  shape_details {
    minimum_bandwidth_in_mbps = local.lb_min_shape
    maximum_bandwidth_in_mbps = local.lb_max_shape
  }
  subnet_ids = [
    local.public_subnet_ocid
  ]
  network_security_group_ids = [
    oci_core_network_security_group.lb.id,
  ]
}

// Autonomous Database
resource "oci_database_autonomous_database" "default_adb" {
  for_each                             = var.byo_db_type == "" ? { managed = true } : {}
  admin_password                       = local.db_conn.password
  autonomous_maintenance_schedule_type = "REGULAR"
  character_set                        = local.adb_is_free_tier ? null : "AL32UTF8"
  compartment_id                       = local.compartment_ocid
  compute_count                        = local.adb_is_free_tier ? 1 : var.adb_ecpu_core_count
  compute_model                        = "ECPU"
  data_storage_size_in_gb              = local.adb_is_free_tier ? 20 : var.adb_data_storage_size_in_gb
  database_edition                     = !local.adb_is_free_tier && var.adb_license_model == "BRING_YOUR_OWN_LICENSE" ? var.adb_edition : null
  db_name                              = local.db_name
  db_version                           = var.adb_version
  db_workload                          = "OLTP"
  display_name                         = local.db_name
  is_free_tier                         = local.adb_is_free_tier
  is_auto_scaling_enabled              = local.adb_is_free_tier ? false : var.adb_is_cpu_auto_scaling_enabled
  is_auto_scaling_for_storage_enabled  = local.adb_is_free_tier ? false : var.adb_is_storage_auto_scaling_enabled
  is_dedicated                         = false
  license_model                        = local.adb_is_free_tier ? "LICENSE_INCLUDED" : var.adb_license_model
  is_mtls_connection_required          = true
  nsg_ids                              = local.adb_nsg
  whitelisted_ips                      = local.adb_whitelist_cidrs
  private_endpoint_label               = local.adb_private_endpoint_label
  subnet_id                            = local.adb_subnet_id
  lifecycle {
    // cannot change from PRIVATE_ENDPOINT_ACCESS to SECURE_ACCESS
    ignore_changes = [whitelisted_ips, private_endpoint_label, subnet_id]
  }
}

resource "oci_objectstorage_bucket" "bucket" {
  for_each       = var.prov_object_storage ? { managed = true } : {}
  compartment_id = local.compartment_ocid
  namespace      = local.object_storage_namespace
  name           = format("%s-bucket", local.label_prefix)
  access_type    = "NoPublicAccess"
  auto_tiering   = "Disabled"
}
