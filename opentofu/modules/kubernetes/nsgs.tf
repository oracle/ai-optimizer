# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

resource "oci_core_network_security_group" "k8s_api_endpoint" {
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = format("%s-k8s-api-endpoint", var.label_prefix)
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}

resource "oci_core_network_security_group" "k8s_workers" {
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = format("%s-k8s-workers", var.label_prefix)
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}