# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// Worker Node Pool
resource "oci_core_network_security_group" "compute" {
  for_each       = var.infrastructure == "VM" ? { "VM" = "VM" } : { "Kubernetes" = "Kubernetes" }
  compartment_id = local.compartment_ocid
  vcn_id         = module.network.vcn_ocid
  display_name   = format("%s-compute", local.label_prefix)
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}