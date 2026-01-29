# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

variable "compartment_id" {
  type = string
}

variable "label_prefix" {
  type = string
}

variable "infra" {
  type = string
}

variable "vcn_cidr" {
  type = map(any)
  default = {
    "VM"         = ["10.42.0.0/27"]
    "Kubernetes" = ["10.42.0.0/16"]
  }
}

variable "oci_services" {
  description = "OCI Services Network object containing id, name, and cidr_block"
  type = object({
    cidr_block = string
    id         = string
    name       = string
  })
}