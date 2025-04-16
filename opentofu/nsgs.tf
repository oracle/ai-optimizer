# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// Load Balancer
resource "oci_core_network_security_group" "lb" {
  compartment_id = local.compartment_ocid
  vcn_id         = module.network.vcn_ocid
  display_name   = format("%s-lb", local.label_prefix)
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}

resource "oci_core_network_security_group_security_rule" "client_lb_ingress" {
  for_each                  = toset(split(",", replace(var.client_allowed_cidrs, "/\\s+/", "")))
  network_security_group_id = oci_core_network_security_group.lb.id
  description               = "Loadbalancer Client Access - ${each.value}."
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = each.value
  source_type               = "CIDR_BLOCK"
  tcp_options {
    destination_port_range {
      min = local.lb_client_port
      max = local.lb_client_port
    }
  }
}

resource "oci_core_network_security_group_security_rule" "server_lb_ingress" {
  for_each                  = toset(split(",", replace(var.server_allowed_cidrs, "/\\s+/", "")))
  network_security_group_id = oci_core_network_security_group.lb.id
  description               = "Loadbalancer Server Access - ${each.value}."
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = each.value
  source_type               = "CIDR_BLOCK"
  tcp_options {
    destination_port_range {
      min = local.lb_server_port
      max = local.lb_server_port
    }
  }
}

resource "oci_core_network_security_group_security_rule" "client_lb_egress" {
  network_security_group_id = oci_core_network_security_group.lb.id
  description               = "Loadbalancer VCN Access."
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = module.network.private_subnet_cidr_block
  destination_type          = "CIDR_BLOCK"
  tcp_options {
    destination_port_range {
      min = local.streamlit_client_port
      max = local.streamlit_client_port
    }
  }
}

resource "oci_core_network_security_group_security_rule" "server_lb_egress" {
  network_security_group_id = oci_core_network_security_group.lb.id
  description               = "Loadbalancer VCN Access."
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = module.network.private_subnet_cidr_block
  destination_type          = "CIDR_BLOCK"
  tcp_options {
    destination_port_range {
      min = local.fastapi_server_port
      max = local.fastapi_server_port
    }
  }
}