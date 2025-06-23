# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable



data "oci_core_images" "images" {
  compartment_id   = var.compartment_id
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

data "oci_core_vcn" "vcn" {
  vcn_id = var.vcn_id
}

data "oci_core_services" "core_services" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}