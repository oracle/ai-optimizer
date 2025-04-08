# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// random
resource "random_pet" "label" {
  length = 1
}

resource "oci_identity_dynamic_group" "node_dynamic_group" {
  compartment_id = var.tenancy_ocid
  name           = format("%s-worker-dyngrp", local.label_prefix)
  description    = format("%s Dynamic Group - Workers", local.label_prefix)
  matching_rule = format(
    "All {instance.id = '%s'}",
    oci_core_instance.instance["VM"].id
  )
  provider = oci.home_region
}

resource "oci_identity_policy" "identity_node_policies" {
  compartment_id = var.tenancy_ocid
  name           = format("%s-worker-instance-policy", local.label_prefix)
  description    = format("%s InstancePrinciple - K8s Nodes", local.label_prefix)
  statements = [
    format(
      "allow dynamic-group %s to use autonomous-database-family in compartment id %s",
      oci_identity_dynamic_group.node_dynamic_group.name, local.compartment_ocid
    ),
    format(
      "allow dynamic-group %s to read objectstorage-namespaces in compartment id %s",
      oci_identity_dynamic_group.node_dynamic_group.name, local.compartment_ocid
    )
  ]
  provider = oci.home_region
}

// Infra = VM 
resource "oci_core_instance" "instance" {
  for_each            = var.infra == "VM" ? { "VM" = "VM" } : {}
  compartment_id      = local.compartment_ocid
  display_name        = format("%s-compute", local.label_prefix)
  availability_domain = local.availability_domains[0]
  shape               = var.worker_cpu_shape
  shape_config {
    memory_in_gbs = var.worker_cpu_ocpu * 16
    ocpus         = var.worker_cpu_ocpu
  }
  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.images.images[0].id
    boot_volume_size_in_gbs = 50
  }
  agent_config {
    are_all_plugins_disabled = false
    is_management_disabled   = false
    is_monitoring_disabled   = false
    plugins_config {
      desired_state = "ENABLED"
      name          = "Bastion"
    }
  }
  create_vnic_details {
    subnet_id        = module.network.public_subnet_ocid
    assign_public_ip = true
    nsg_ids          = [oci_core_network_security_group.workers.id]
  }
  metadata = {
    user_data = "${base64encode(local.cloud_init)}"
  }
  lifecycle {
    create_before_destroy = true
    ignore_changes        = [source_details.0.source_id]
  }
}