# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

terraform {
  required_providers {
    oci = {
      source = "oracle/oci"
    }
  }
}

resource "oci_core_vcn" "vcn" {
  compartment_id = var.compartment_id
  cidr_blocks    = [var.vcn_cidr]
  display_name   = format("%s-vcn", var.label_prefix)
  dns_label      = var.label_prefix
  lifecycle {
    ignore_changes = [
      cidr_blocks,
    ]
  }
}

// Lock Down Default Sec List
resource "oci_core_default_security_list" "lockdown" {
  compartment_id             = oci_core_vcn.vcn.compartment_id
  display_name               = format("%s-default-sec-list", var.label_prefix)
  manage_default_resource_id = oci_core_vcn.vcn.default_security_list_id
}

// Public Subnet
resource "oci_core_internet_gateway" "igw" {
  compartment_id = oci_core_vcn.vcn.compartment_id
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = format("%s-igw", var.label_prefix)
  enabled        = "true"
}

resource "oci_core_default_route_table" "public_route_table" {
  display_name = format("%s-public-route-table", var.label_prefix)
  route_rules {
    description       = "traffic to/from internet"
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
  manage_default_resource_id = oci_core_vcn.vcn.default_route_table_id
}

resource "oci_core_subnet" "public" {
  cidr_block                 = cidrsubnet(one(oci_core_vcn.vcn.cidr_blocks), 1, 1)
  compartment_id             = oci_core_vcn.vcn.compartment_id
  vcn_id                     = oci_core_vcn.vcn.id
  display_name               = format("%s-public", var.label_prefix)
  dns_label                  = oci_core_vcn.vcn.dns_label == null ? null : "publ"
  prohibit_public_ip_on_vnic = false
  route_table_id             = oci_core_default_route_table.public_route_table.id
  lifecycle {
    ignore_changes = [
      cidr_block,
    ]
  }
}

// Private Subnet
resource "oci_core_nat_gateway" "ngw" {
  compartment_id = oci_core_vcn.vcn.compartment_id
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = format("%s-ngw", var.label_prefix)
  block_traffic  = "false"
}

resource "oci_core_service_gateway" "sgw" {
  compartment_id = oci_core_vcn.vcn.compartment_id
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = format("%s-sgw", var.label_prefix)
  services {
    service_id = data.oci_core_services.core_services.services.0.id
  }
}

resource "oci_core_route_table" "private_route_table" {
  compartment_id = oci_core_vcn.vcn.compartment_id
  vcn_id         = oci_core_vcn.vcn.id
  display_name   = format("%s-private-route-table", var.label_prefix)
  route_rules {
    description       = "traffic to the internet"
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.ngw.id
  }
  route_rules {
    description       = "traffic to OCI services"
    destination       = data.oci_core_services.core_services.services.0.cidr_block
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.sgw.id
  }
  lifecycle {
    ignore_changes = all
  }
}

resource "oci_core_subnet" "private" {
  cidr_block                 = cidrsubnet(one(oci_core_vcn.vcn.cidr_blocks), 1, 0)
  compartment_id             = oci_core_vcn.vcn.compartment_id
  vcn_id                     = oci_core_vcn.vcn.id
  display_name               = format("%s-private", var.label_prefix)
  dns_label                  = oci_core_vcn.vcn.dns_label == null ? null : "priv"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private_route_table.id
  lifecycle {
    ignore_changes = [
      cidr_block,
    ]
  }
}