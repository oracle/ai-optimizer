# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

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

resource "oci_identity_dynamic_group" "resource_dynamic_group" {
  compartment_id = var.tenancy_ocid
  name           = format("%s-dyngrp", local.label_prefix)
  description    = format("%s Dynamic Group", local.label_prefix)
  matching_rule = format(
    "All {resource.compartment.id = '%s', tag.%s.value = '%s'}",
    local.compartment_ocid, local.identity_tag_key, local.label_prefix
  )
  provider = oci.home_region
}

resource "oci_identity_policy" "adb_policies" {
  compartment_id = var.tenancy_ocid
  name           = format("%s-adb-policy", var.label_prefix)
  description    = format("%s - ADB", var.label_prefix)
  statements = [
    format("allow dynamic-group %s to use generative-ai-family in compartment id %s", oci_identity_dynamic_group.resource_dynamic_group.name, local.compartment_ocid),
  ]
  provider = oci.home_region
}