resource "oci_core_network_security_group" "compute" {
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = format("%s-compute", var.label_prefix)
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}

// Rules
resource "oci_core_network_security_group_security_rule" "vcn_tcp_ingress" {
  network_security_group_id = oci_core_network_security_group.compute.id
  description               = "Compute VCN Access - TCP Ingress."
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = data.oci_core_vcn.vcn.cidr_block
  source_type               = "CIDR_BLOCK"
}

resource "oci_core_network_security_group_security_rule" "vcn_icmp_ingress" {
  network_security_group_id = oci_core_network_security_group.compute.id
  description               = "Compute Path Discovery - ICMP Ingress."
  direction                 = "INGRESS"
  protocol                  = "1"
  source                    = data.oci_core_vcn.vcn.cidr_block
  source_type               = "CIDR_BLOCK"
}

resource "oci_core_network_security_group_security_rule" "vcn_icmp_egress" {
  network_security_group_id = oci_core_network_security_group.compute.id
  description               = "Compute Path Discovery - ICMP Egress."
  direction                 = "EGRESS"
  protocol                  = "1"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
}

resource "oci_core_network_security_group_security_rule" "vcn_tcp_egress" {
  network_security_group_id = oci_core_network_security_group.compute.id
  description               = "Compute Anywhere - TCP Egress."
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
}