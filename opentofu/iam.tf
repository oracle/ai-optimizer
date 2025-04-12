# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// Tags for instance/workload principles
resource "oci_identity_tag_namespace" "tag_namespace" {
  compartment_id = local.compartment_ocid
  description    = format("%s Tag Namespace", local.label_prefix)
  name           = local.label_prefix
  provider       = oci.home_region
}

resource "oci_identity_tag" "identity_tag" {
  description      = format("%s Infrastructure", local.label_prefix)
  name             = "infrastructure"
  tag_namespace_id = oci_identity_tag_namespace.tag_namespace.id
  provider         = oci.home_region
}

resource "oci_identity_dynamic_group" "compute_dynamic_group" {
  compartment_id = var.tenancy_ocid
  name           = format("%s-compute-dyngrp", local.label_prefix)
  description    = format("%s Dynamic Group - Computes", local.label_prefix)
  matching_rule = format(
    "All {instance.compartment.id = '%s', tag.%s.value = '%s'}",
    local.compartment_ocid, local.identity_tag_key, local.identity_tag_val
  )
  provider = oci.home_region
}

resource "oci_identity_policy" "identity_node_policies" {
  compartment_id = var.tenancy_ocid
  name           = format("%s-compute-instance-policy", local.label_prefix)
  description    = format("%s InstancePrinciples", local.label_prefix)
  statements = [
    format(
      "allow dynamic-group %s to use autonomous-database-family in compartment id %s",
      oci_identity_dynamic_group.compute_dynamic_group.name, local.compartment_ocid
    ),
    format(
      "allow dynamic-group %s to read objectstorage-namespaces in compartment id %s",
      oci_identity_dynamic_group.compute_dynamic_group.name, local.compartment_ocid
    ),
    format(
      "allow dynamic-group %s to inspect buckets in compartment id %s",
      oci_identity_dynamic_group.compute_dynamic_group.name, local.compartment_ocid
    ),
    format(
      "allow dynamic-group %s to read objects in compartment id %s",
      oci_identity_dynamic_group.compute_dynamic_group.name, local.compartment_ocid
    ),
  ]
  provider = oci.home_region
}