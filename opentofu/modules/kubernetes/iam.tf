# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

resource "oci_identity_tag_namespace" "tag_namespace" {
  compartment_id = var.compartment_id
  description    = format("%s Tag Namespace", var.label_prefix)
  name           = var.label_prefix
  provider       = oci.home_region
}

resource "oci_identity_tag" "identity_tag" {
  description      = format("%s Infrastructure", var.label_prefix)
  name             = "infrastructure"
  tag_namespace_id = oci_identity_tag_namespace.tag_namespace.id
  provider         = oci.home_region
}

resource "oci_identity_dynamic_group" "compute_dynamic_group" {
  compartment_id = var.tenancy_id
  name           = format("%s-compute-dyngrp", var.label_prefix)
  description    = format("%s Dynamic Group - Computes", var.label_prefix)
  matching_rule = format(
    "All {instance.compartment.id = '%s', tag.%s.value = '%s'}",
    var.compartment_id, local.identity_tag_key, local.identity_tag_val
  )
  provider = oci.home_region
}