# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

variable "byo_vcn_ocid" {
  description = "Bring Your Own Virtual Cloud Network - VCN OCID"
  type        = string
  default     = ""
}

variable "byo_public_subnet_ocid" {
  description = "Bring Your Own Virtual Cloud Network - Pubic Subnet OCID"
  type        = string
  default     = ""
}

variable "byo_private_subnet_ocid" {
  description = "Bring Your Own Virtual Cloud Network - Private Subnet OCID"
  type        = string
  default     = ""
}

module "network" {
  for_each       = var.byo_vcn_ocid == "" ? { managed = true } : {}
  source         = "./modules/network"
  compartment_id = local.compartment_ocid
  label_prefix   = local.label_prefix
  infra          = var.infrastructure
  oci_services   = data.oci_core_services.core_services.services.0

}