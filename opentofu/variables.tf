# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

#########################################################################
# NOTE!! Variables specific to modules are in thier own module_*.tf file
#########################################################################

// Standard Default Vars
variable "optimizer_version" {
  description = "Determines if latest release or main code line is used"
  type        = string
  default     = "Stable"
  validation {
    condition     = var.optimizer_version == "Stable" || var.optimizer_version == "Experimental"
    error_message = "optimizer_version must be either 'Stable' or 'Experimental'."
  }
}

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
  description = "DO NOT SET!  This is strictly used for OCI ORM Installs."
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

// Infrastructure Type/Label
variable "label_prefix" {
  description = "Alpha Numeric (less than 12 characters) string that will be prepended to all resources. Leave blank to auto-generate."
  type        = string
  default     = ""
  validation {
    condition     = can(regex("^[a-zA-Z0-9]*$", var.label_prefix)) || length(var.label_prefix) < 12
    error_message = "Must be Alpha Numeric and less than 12 characters."
  }
}

variable "infrastructure" {
  description = "Choose between a full Kubernetes or a light-weight Virtual Machine deployment."
  type        = string
  default     = "VM"
  validation {
    condition     = contains(["Kubernetes", "VM"], var.infrastructure)
    error_message = "Must be either Kubernetes or VM."
  }
}

// Database
variable "byo_db_type" {
  description = "Bring Your Own Database - Type"
  type        = string
  default     = ""
  validation {
    condition     = contains(["", "ADB-S", "OTHER"], var.byo_db_type)
    error_message = "Must be either ADB-S or OTHER."
  }
}

variable "byo_db_password" {
  description = "Bring Your Own Database - Password"
  type        = string
  default     = ""
  sensitive   = true
}

variable "byo_adb_ocid" {
  description = "Bring Your Own Autonomous Database - OCID"
  type        = string
  default     = ""
}

variable "byo_odb_host" {
  description = "Bring Your Own Other Database - Hostname"
  type        = string
  default     = ""
}

variable "byo_odb_port" {
  description = "Bring Your Own Other Database - Port"
  type        = number
  default     = 1521
}

variable "byo_odb_service" {
  description = "Bring Your Own Other Database - Service Name"
  type        = string
  default     = ""
}

variable "adb_version" {
  description = "Autonomous Database Version"
  type        = string
  default     = "26ai"
  validation {
    condition     = contains(["26ai"], var.adb_version)
    error_message = "Must be 26ai."
  }
}

variable "adb_ecpu_core_count" {
  description = "Choose how many ECPU cores will be elastically allocated."
  type        = number
  default     = 2
  validation {
    condition     = var.adb_ecpu_core_count >= 2 && var.adb_ecpu_core_count <= 512
    error_message = "ADB ECPU count must be between 2 and 512"
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
  default     = ""
  validation {
    condition     = can(regex("$|((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])/(3[0-2]|[1-2]?[0-9])(,?)( ?)){1,}$", var.adb_whitelist_cidrs))
    error_message = "Must be a comma separated string of valid CIDRs."
  }
}

variable "adb_networking" {
  description = "Choose the Autonomous Database Network Access."
  type        = string
  default     = "SECURE_ACCESS"
  validation {
    condition     = contains(["PRIVATE_ENDPOINT_ACCESS", "SECURE_ACCESS"], var.adb_networking)
    error_message = "Must be either PRIVATE_ENDPOINT_ACCESS or SECURE_ACCESS."
  }
}

// Compute - Either VM or Node Workers
variable "compute_cpu_shape" {
  description = "Choose the shape of the CPU Computes."
  type        = string
  default     = "VM.Standard.E5.Flex"
  validation {
    condition     = contains(["VM.Standard.E5.Flex", "VM.Standard.E4.Flex", "VM.Standard.A1.Flex", "VM.Standard.A2.Flex", ], var.compute_cpu_shape)
    error_message = "Must be either VM.Standard.E5.Flex, VM.Standard.E4.Flex, VM.Standard.A1.Flex, or VM.Standard.A2.Flex"
  }
}

variable "compute_cpu_ocpu" {
  description = "The initial number of CPU(s) for the Computes."
  type        = number
  default     = 2
}

variable "compute_gpu_shape" {
  description = "Choose the shape of the GPU Computes."
  type        = string
  default     = "VM.GPU.A10.1"
  validation {
    condition     = contains(["VM.GPU.A10.1", "VM.GPU.A10.2"], var.compute_gpu_shape)
    error_message = "Must be either VM.GPU.A10.1, or VM.GPU.A10.2."
  }
}

// LoadBalancer
variable "lb_min_shape" {
  description = "LoadBalancer minimum bandwidth (Mbps)."
  type        = number
  default     = 10
}

variable "lb_max_shape" {
  description = "LoadBalancer maximum bandwidth (Mbps)."
  type        = number
  default     = 10
}

// NSGs
variable "client_allowed_cidrs" {
  description = "Comma separated string of CIDR blocks from which the application client can be accessed."
  type        = string
  default     = "0.0.0.0/0"
  validation {
    condition     = can(regex("$|((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])/(3[0-2]|[1-2]?[0-9])(,?)( ?)){1,}$", var.client_allowed_cidrs))
    error_message = "Must be a comma separated string of valid CIDRs."
  }
}

variable "server_allowed_cidrs" {
  description = "Comma separated string of CIDR blocks from which the application server can be accessed."
  type        = string
  default     = "0.0.0.0/0"
  validation {
    condition     = can(regex("$|((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9]).(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])/(3[0-2]|[1-2]?[0-9])(,?)( ?)){1,}$", var.server_allowed_cidrs))
    error_message = "Must be a comma separated string of valid CIDRs."
  }
}