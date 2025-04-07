# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable
locals {
  adb_whitelist_cidrs = concat(split(",", replace(var.adb_whitelist_cidrs, "/\\s+/", "")), [module.network.vcn_ocid])
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

resource "oci_database_autonomous_database" "default_adb" {
  admin_password                       = sensitive(format("%s%s", random_password.adb_char.result, random_password.adb_rest.result))
  autonomous_maintenance_schedule_type = "REGULAR"
  character_set                        = "AL32UTF8"
  compartment_id                       = local.compartment_ocid
  compute_count                        = var.adb_ecpu_core_count
  compute_model                        = "ECPU"
  data_storage_size_in_gb              = var.adb_data_storage_size_in_gb
  database_edition                     = var.adb_license_model == "BRING_YOUR_OWN_LICENSE" ? var.adb_edition : null
  db_name                              = format("%sDB", upper(local.label_prefix))
  db_version                           = var.adb_version
  db_workload                          = "OLTP"
  display_name                         = format("%sDB", upper(local.label_prefix))
  is_free_tier                         = false
  is_auto_scaling_enabled              = var.adb_is_cpu_auto_scaling_enabled
  is_auto_scaling_for_storage_enabled  = var.adb_is_storage_auto_scaling_enabled
  is_dedicated                         = false
  license_model                        = var.adb_license_model
  is_mtls_connection_required          = true
  whitelisted_ips                      = local.adb_whitelist_cidrs
}