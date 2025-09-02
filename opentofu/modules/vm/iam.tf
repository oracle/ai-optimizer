# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

resource "oci_identity_dynamic_group" "compute_dynamic_group" {
  compartment_id = var.tenancy_id
  name           = format("%s-compute-dyngrp", var.label_prefix)
  description    = format("%s Dynamic Group - Computes", var.label_prefix)
  matching_rule = format(
    "All {instance.compartment.id = '%s', instance.id = '%s'}",
    var.compartment_id, oci_core_instance.instance.id
  )
  provider = oci.home_region
}

resource "oci_identity_policy" "identity_node_policies" {
  compartment_id = var.tenancy_id
  name           = format("%s-compute-instance-policy", var.label_prefix)
  description    = format("%s InstancePrinciples", var.label_prefix)
  statements = [
    format(
      "allow dynamic-group %s to use autonomous-database-family in compartment id %s",
      oci_identity_dynamic_group.compute_dynamic_group.name, var.compartment_id
    ),
    format(
      "allow dynamic-group %s to read objectstorage-namespaces in compartment id %s",
      oci_identity_dynamic_group.compute_dynamic_group.name, var.compartment_id
    ),
    format(
      "allow dynamic-group %s to inspect buckets in compartment id %s",
      oci_identity_dynamic_group.compute_dynamic_group.name, var.compartment_id
    ),
    format(
      "allow dynamic-group %s to read objects in compartment id %s",
      oci_identity_dynamic_group.compute_dynamic_group.name, var.compartment_id
    ),
    format(
      "allow dynamic-group %s to use generative-ai-family in compartment id %s", 
      oci_identity_dynamic_group.workers_dynamic_group.name, var.compartment_id
    ),
  ]
  provider = oci.home_region
}