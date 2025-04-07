# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

variable "compartment_id" {
  type = string
}

variable "label_prefix" {
  type = string
}

variable "vcn_cidr" {
  type    = string
  default = "10.42.0.0/16"
}