# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "images" {
  for_each         = var.infrastructure == "VM" ? { "VM" = "VM" } : {}
  compartment_id   = local.compartment_ocid
  operating_system = "Oracle Linux"
  shape            = var.compute_cpu_shape

  filter {
    name   = "display_name"
    values = ["Oracle-Linux-${var.compute_os_ver}-.*"]
    regex  = true
  }

  sort_by    = "TIMECREATED"
  sort_order = "DESC"
}