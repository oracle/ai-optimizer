# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

variable "optimizer_version" {
  type = string
}

variable "optimizer_branch" {
  type = string
}

variable "app_version" {
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

variable "compute_install_ollama" {
  type    = bool
  default = false
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

variable "compute_cpu_memory_gbs" {
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
  validation {
    condition = alltrue([
      trimspace(var.db_conn.username) != "",
      trimspace(var.db_conn.password) != "",
      trimspace(var.db_conn.service) != "",
    ])
    error_message = "db_conn must provide a non-empty username, password, and service."
  }
}

variable "lb_client_http_port" {
  type = number
}

variable "lb_client_https_port" {
  type = number
}

variable "lb_server_http_port" {
  type = number
}

variable "lb_server_https_port" {
  type = number
}

variable "ssl_enabled" {
  type    = bool
  default = false
}

variable "ssl_cert_pem" {
  type      = string
  default   = ""
  sensitive = true
}

variable "ssl_key_pem" {
  type      = string
  default   = ""
  sensitive = true
}

variable "ssl_ca_cert" {
  type      = string
  default   = ""
  sensitive = true
}

variable "client_cookie_secret" {
  description = "Streamlit signed-cookie key stored in .env.vm so the value remains stable across systemd restarts."
  type        = string
  sensitive   = true
}

variable "object_storage_bucket" {
  type    = string
  default = ""
}
