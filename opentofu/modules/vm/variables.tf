# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

variable "optimizer_version" {
  type = string
}

variable "tenancy_id" {
  type = string
}

variable "compartment_id" {
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

variable "oci_services" {
  type = object({
    cidr_block = string
    id         = string
    name       = string
  })
}

variable "private_subnet_id" {
  type = string
}

variable "vm_is_gpu_shape" {
  type = bool
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

variable "compute_gpu_shape" {
  type = string
}

variable "db_name" {
  type = string
}

variable "db_conn" {
  type = object({
    db_type  = string
    username = string
    password = string
    service  = string
  })
}

variable "lb_client_port" {
  type = number
}

variable "lb_server_port" {
  type = number
}