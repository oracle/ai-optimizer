# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

variable "tenancy_ocid" {
  description = "The Tenancy ID of the OCI Cloud Account in which to create the resources."
  type        = string
}

variable "compartment_ocid" {
  description = "The compartment in which to create OCI Resources."
  type        = string
}

variable "region" {
  description = "The OCI Region where resources will be created."
  type        = string
}

variable "user_ocid" {
  description = "The ID of the User that terraform will use to create the resources."
  type        = string
  default     = ""
}

variable "current_user_ocid" {
  description = "The ID of the user that terraform will use to create the resources. ORM compatible"
  type        = string
  default     = ""
}

variable "fingerprint" {
  description = "Fingerprint of the API private key to use with OCI API."
  type        = string
  default     = ""
}

variable "private_key" {
  description = "The contents of the private key file to use with OCI API. This takes precedence over private_key_path if both are specified in the provider."
  sensitive   = true
  type        = string
  default     = null
}

variable "private_key_path" {
  description = "The path to the OCI API private key."
  type        = string
  default     = ""
}

variable "label_prefix" {
  description = "Alpha Numeric (less than 12 characters) string that will be prepended to all resources. Leave blank to auto-generate."
  type        = string
  default     = ""
  validation {
    condition     = can(regex("^[a-zA-Z0-9]*$", var.label_prefix)) || length(var.label_prefix) < 12
    error_message = "Must be Alpha Numeric and less than 12 characters."
  }
}

// K8s Cluster
variable "k8s_version" {
  description = "The version of Kubernetes to install into the cluster masters."
  type        = string
  default     = "1.32.1"
}

variable "k8s_api_is_public" {
  type    = bool
  default = false
}

# This is a string and not a list to support ORM/MP input, it will be converted to a list in locals
variable "k8s_api_endpoint_allowed_cidrs" {
  description = "Comma separated string of CIDR blocks from which the API Endpoint can be accessed."
  type        = string
  default     = "0.0.0.0/0"
  validation {
    condition     = can(regex("$|((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])/(3[0-2]|[1-2]?[0-9])(,?)( ?)){1,}$", var.k8s_api_endpoint_allowed_cidrs))
    error_message = "Must be a comma separated string of valid CIDRs."
  }
}

variable "k8s_worker_os_ver" {
  description = "Oracle Linux Version for K8s Node Pool Workers"
  type        = string
  default     = "8.10"
}

variable "k8s_node_pool_cpu_size" {
  description = "Number of Workers in the CPU Node Pool."
  type        = number
  default     = 2
}

variable "k8s_worker_cpu_shape" {
  description = "Choose the shape of the CPU Node Pool Workers."
  type        = string
  default     = "VM.Standard.E5.Flex"
  validation {
    condition     = contains(["VM.Standard.E5.Flex", "VM.Standard.E4.Flex", "VM.Standard3.Flex"], var.k8s_worker_cpu_shape)
    error_message = "Must be either VM.Standard.E5.Flex, VM.Standard.E4.Flex, or VM.Standard3.Flex."
  }
}

variable "k8s_worker_cpu_ocpu" {
  description = "The initial number of CPU(s) for the Node Pool Workers."
  type        = number
  default     = 2
}

// GPU Node Pool
variable "k8s_node_pool_gpu_deploy" {
  description = "Deploy a GPU Node Pool"
  type        = bool
  default     = true
}

variable "k8s_node_pool_gpu_size" {
  description = "Number of Workers in the GPU Node Pool."
  type        = number
  default     = 1
}

variable "k8s_worker_gpu_shape" {
  description = "Choose the shape of the GPU Node Pool Workers."
  type        = string
  default     = "VM.GPU.A10.1"
  validation {
    condition     = contains(["VM.GPU.A10.1", "VM.GPU.A10.2"], var.k8s_worker_gpu_shape)
    error_message = "Must be either VM.GPU.A10.1, or VM.GPU.A10.2."
  }
}

// LoadBalancer
variable "service_lb_is_public" {
  type    = bool
  default = true
}

variable "service_lb_min_shape" {
  default = 10
}

variable "service_lb_max_shape" {
  default = 1250
}

variable "service_lb_allowed_app_client_cidrs" {
  description = "Comma separated string of CIDR blocks from which the application GUI can be accessed."
  type        = string
  default     = "0.0.0.0/0"
  validation {
    condition     = can(regex("((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])/(3[0-2]|[1-2]?[0-9])(,?)( ?)){1,}$", var.service_lb_allowed_app_client_cidrs))
    error_message = "Must be a comma separated string of valid CIDRs."
  }
}

variable "service_lb_allowed_app_client_port" {
  description = "Port from which the application GUI can be accessed."
  type        = string
  default     = "80"
  validation {
    condition     = can(regex("^(((6553[0-5])|(655[0-2][0-9])|(65[0-4][0-9]{2})|(6[0-4][0-9]{3})|([1-5][0-9]{4})|([0-5]{0,5})|([0-9]{1,4})))$", var.service_lb_allowed_app_client_port))
    error_message = "Must be a single valid port."
  }
}

variable "service_lb_allowed_app_server_cidrs" {
  description = "Comma separated string of CIDR blocks from which the application API Server can be accessed."
  type        = string
  default     = "0.0.0.0/0"
  validation {
    condition     = can(regex("((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])/(3[0-2]|[1-2]?[0-9])(,?)( ?)){1,}$", var.service_lb_allowed_app_server_cidrs))
    error_message = "Must be a comma separated string of valid CIDRs."
  }
}

variable "service_lb_allowed_app_server_port" {
  description = "Port from which the application API Server can be accessed."
  type        = string
  default     = "8000"
  validation {
    condition     = can(regex("^(((6553[0-5])|(655[0-2][0-9])|(65[0-4][0-9]{2})|(6[0-4][0-9]{3})|([1-5][0-9]{4})|([0-5]{0,5})|([0-9]{1,4})))$", var.service_lb_allowed_app_server_port))
    error_message = "Must be a single valid port."
  }
}

// Database
variable "adb_version" {
  description = "Autonomous Database Version"
  type        = string
  default     = "23ai"
  validation {
    condition     = contains(["23ai"], var.adb_version)
    error_message = "Must be 23ai."
  }
}

variable "adb_ecpu_core_count" {
  description = "Choose how many ECPU cores will be elastically allocated."
  type        = number
  default     = 2
  validation {
    condition     = var.adb_ecpu_core_count >= 2
    error_message = "Must be equal or greater than 2."
  }
}

variable "adb_data_storage_size_in_gb" {
  description = "Choose ADB Database Data Storage Size in gigabytes."
  type        = number
  default     = 20
  validation {
    condition     = var.adb_data_storage_size_in_gb >= 20 && var.adb_data_storage_size_in_gb <= 393216
    error_message = "Must be equal or greater than 20 and equal or less than 393216."
  }
}

variable "adb_is_cpu_auto_scaling_enabled" {
  type    = bool
  default = true
}

variable "adb_is_storage_auto_scaling_enabled" {
  type    = bool
  default = true
}

variable "adb_license_model" {
  description = "Choose Autonomous Database license model."
  type        = string
  default     = "LICENSE_INCLUDED"
  validation {
    condition     = contains(["LICENSE_INCLUDED", "BRING_YOUR_OWN_LICENSE"], var.adb_license_model)
    error_message = "Must be either LICENSE_INCLUDED or BRING_YOUR_OWN_LICENSE."
  }
}

variable "adb_edition" {
  # Only Applicable when adb_license_model=BYOL
  description = "Oracle Database Edition that applies to the Autonomous databases (BYOL)."
  type        = string
  default     = "ENTERPRISE_EDITION"
  validation {
    condition     = contains(["", "ENTERPRISE_EDITION", "STANDARD_EDITION"], var.adb_edition)
    error_message = "Must be either ENTERPRISE_EDITION or STANDARD_EDITION."
  }
}

variable "adb_whitelist_cidrs" {
  # This is a string and not a list to support ORM/MP input, it will be converted to a list in locals
  description = "Comma separated string of CIDR blocks from which the ADB can be accessed."
  type        = string
  default     = "0.0.0.0/0"
  validation {
    condition     = can(regex("$|((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])/(3[0-2]|[1-2]?[0-9])(,?)( ?)){1,}$", var.adb_whitelist_cidrs))
    error_message = "Must be a comma separated string of valid CIDRs."
  }
}
