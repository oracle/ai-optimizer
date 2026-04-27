# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

variable "k8s_api_is_public" {
  description = "Make K8s API endpoint accessible from external networks via NSG rules. If false, only ORM deployments can apply Helm automatically."
  type        = bool
  default     = true
}

variable "k8s_api_endpoint_allowed_cidrs" {
  description = "Comma separated string of CIDR blocks from which the Kubernetes API endpoint can be accessed. Leave empty to avoid public API ingress; local configuration management requires a reachable source CIDR, typically your public IP as /32."
  type        = string
  default     = ""
  validation {
    condition = trimspace(var.k8s_api_endpoint_allowed_cidrs) == "" || alltrue([
      for cidr in split(",", replace(var.k8s_api_endpoint_allowed_cidrs, "/\\s+/", "")) : can(cidrnetmask(cidr))
    ])
    error_message = "Must be empty or a comma separated string of valid CIDRs."
  }
}

variable "k8s_cpu_node_pool_size" {
  description = "Number of Workers in the CPU Node Pool."
  type        = number
  default     = 2
}

variable "k8s_node_pool_gpu_deploy" {
  description = "Deploy a GPU Node Pool?"
  type        = bool
  default     = false
}

variable "k8s_gpu_node_pool_size" {
  description = "Number of Workers in the GPU Node Pool."
  type        = number
  default     = 1
}

variable "k8s_run_cfgmgt" {
  description = "Run Configuration Management Scripts?"
  type        = bool
  default     = true
}

variable "k8s_byo_ocir_url" {
  description = "BYO Oracle Cluster Image Repository URL"
  type        = string
  default     = ""
}

locals {
  k8s_api_endpoint_allowed_cidrs = [
    for cidr in split(",", replace(var.k8s_api_endpoint_allowed_cidrs, "/\\s+/", "")) : cidr
    if cidr != ""
  ]
  k8s_api_endpoint_reachable_cidrs = [
    for cidr in local.k8s_api_endpoint_allowed_cidrs : cidr
    if length(regexall("^127\\.", cidr)) == 0
  ]
}

# Validation: Configuration management requires either public API endpoint or ORM installation
resource "terraform_data" "k8s_cfgmgt_validation" {
  count = var.infrastructure == "Kubernetes" ? 1 : 0

  lifecycle {
    precondition {
      condition = (
        !var.k8s_run_cfgmgt ||
        var.current_user_ocid != "" ||
        (var.k8s_api_is_public && length(local.k8s_api_endpoint_reachable_cidrs) > 0)
      )
      error_message = "Local Kubernetes configuration management requires a reachable public API endpoint. Set k8s_api_endpoint_allowed_cidrs to your source CIDR, typically your public IP as /32, set k8s_run_cfgmgt=false, or deploy through OCI Resource Manager."
    }
  }
}

module "kubernetes" {
  for_each                   = var.infrastructure == "Kubernetes" ? { managed = true } : {}
  source                     = "./modules/kubernetes"
  label_prefix               = local.label_prefix
  tenancy_id                 = var.tenancy_ocid
  compartment_id             = local.compartment_ocid
  vcn_id                     = local.vcn_ocid
  oci_services               = data.oci_core_services.core_services.services.0
  region                     = var.region
  lb                         = oci_load_balancer_load_balancer.lb
  db_ocid                    = local.db_ocid
  db_name                    = local.db_name
  db_conn                    = local.db_conn
  api_is_public              = var.k8s_api_is_public
  node_pool_gpu_deploy       = var.k8s_node_pool_gpu_deploy
  gpu_node_pool_size         = var.k8s_gpu_node_pool_size
  kubernetes_version         = local.k8s_version
  cpu_node_pool_size         = var.k8s_cpu_node_pool_size
  api_endpoint_allowed_cidrs = var.k8s_api_endpoint_allowed_cidrs
  run_cfgmgt                 = var.k8s_run_cfgmgt
  compute_os_ver             = local.k8s_node_os_ver
  compute_cpu_ocpu           = var.compute_cpu_ocpu
  compute_gpu_shape          = var.compute_gpu_shape
  compute_cpu_shape          = var.compute_cpu_shape
  availability_domains       = local.availability_domains
  public_subnet_id           = local.public_subnet_ocid
  private_subnet_id          = local.private_subnet_ocid
  lb_nsg_id                  = oci_core_network_security_group.lb.id
  orm_install                = var.current_user_ocid != ""
  byo_ocir_url               = var.k8s_byo_ocir_url
  optimizer_version          = var.optimizer_version
  optimizer_branch           = local.optimizer_branch
  ssl_enabled                = local.ssl_enabled
  ssl_cert_pem               = local.ssl_cert_pem
  ssl_key_pem                = local.ssl_key_pem
  client_cookie_secret       = random_password.client_cookie.result
  providers = {
    oci.home_region = oci.home_region
  }
}

output "kubeconfig_cmd" {
  description = "Command to generate kubeconfig file"
  value       = var.infrastructure == "Kubernetes" ? module.kubernetes["managed"].kubeconfig_cmd : "N/A"
}
