# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// VCN
output "vcn_ocid" {
  description = "VCN Identifier."
  value       = oci_core_vcn.vcn.id
}

output "vcn_cidr_block" {
  description = "VCN CIDR Block."
  value       = one(oci_core_vcn.vcn.cidr_blocks)
}

// Private Subnet
output "private_subnet_ocid" {
  description = "Private Subnet Identifier."
  value       = oci_core_subnet.private.id
}

output "private_subnet_cidr_block" {
  description = "Private Subnet CIDR Block."
  value       = oci_core_subnet.private.cidr_block
}

// Public Subnet
output "public_subnet_ocid" {
  description = "Public Subnet Identifier."
  value       = oci_core_subnet.public.id
}

output "public_subnet_cidr_block" {
  description = "Public Subnet CIDR Block."
  value       = oci_core_subnet.public.cidr_block
}