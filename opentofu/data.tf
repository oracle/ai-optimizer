# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_services" "core_services" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

data "oci_database_autonomous_database" "byo_adb" {
  for_each               = var.byo_db_type == "ADB-S" ? { byo = true } : {}
  autonomous_database_id = var.byo_adb_ocid
}

data "oci_core_subnet" "byo_vcn_private" {
  count     = var.byo_vcn_ocid != "" ? 1 : 0
  subnet_id = var.byo_private_subnet_ocid
}