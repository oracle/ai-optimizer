# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

variable "tenancy_id" {
  type = string
}

variable "compartment_id" {
  type = string
}

variable "vcn_id" {
  type = string
}

variable "public_subnet_id" {
  type = string
}

variable "private_subnet_id" {
  type = string
}

variable "lb" {
  type = object({
    id             = string
    compartment_id = string
    ip_address_details = list(object({
      ip_address = string
    }))
    shape_details = list(object({
      minimum_bandwidth_in_mbps = number
      maximum_bandwidth_in_mbps = number
    }))
  })
}

variable "region" {
  type = string
}

variable "availability_domains" {
  type = list(any)
}

variable "label_prefix" {
  type = string
}

variable "adb_id" {
  type = string
}

variable "adb_name" {
  type = string
}

variable "adb_password" {
  type = string
}

variable "k8s_version" {
  type = string
}

variable "k8s_api_is_public" {
  type = bool
}
variable "k8s_node_pool_gpu_deploy" {
  type = bool
}

variable "k8s_cpu_node_pool_size" {
  type = number
}

variable "k8s_gpu_node_pool_size" {
  type = number
}

variable "compute_gpu_shape" {
  type = string
}

variable "compute_os_ver" {
  type = string
}

variable compute_cpu_arch  {
  type = string
}

variable "compute_cpu_shape" {
  type = string
}

variable "compute_cpu_ocpu" {
  type = number
}

variable "lb_nsg_id" {
  type = string
}

variable "k8s_api_endpoint_allowed_cidrs" {
  type    = string
  default = ""
}

variable "k8s_run_cfgmgt" {
  type = bool
}