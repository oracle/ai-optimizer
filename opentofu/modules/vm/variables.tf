# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

variable "tenancy_id" {
  type = string
}

variable "compartment_id" {
  type = string
}

variable "region" {
  type = string
}

variable "label_prefix" {
  type = string
}

variable "lb_id" {
  type = string
}

variable "availability_domains" {
  type = list(any)
}
variable "vcn_id" {
  type = string
}

variable "private_subnet_id" {
  type = string
}
variable "compute_os_ver" {
  type = string
}

variable "compute_cpu_shape" {
  type = string
}

variable "compute_cpu_ocpu" {
  type = number
}

variable "adb_name" {
  type = string
}

variable "adb_password" {
  type = string
}

variable "streamlit_client_port" {
  type = number
}

variable "fastapi_server_port" {
  type = number
}

variable "lb_client_port" {
  type = number
}

variable "lb_server_port" {
  type = number
}