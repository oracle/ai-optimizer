# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// Oracle Resource Manager
locals {
  create_orm_pe = var.orm_install ? contains(local.api_endpoint_allowed_cidrs, "0.0.0.0/0") ? false : true : false
  orm_pe        = local.create_orm_pe ? data.oci_resourcemanager_private_endpoint_reachable_ip.orm_pe_reachable_ip[0].ip_address : ""
}

// Configuration Management Validation
locals {
  can_apply_cfgmgt         = var.api_is_public || var.orm_install
  should_show_manual_steps = var.run_cfgmgt && !local.can_apply_cfgmgt

  cfgmgt_error_message = <<-EOT
    Cannot run configuration management (Helm/kubectl) with a private K8s API endpoint from local Terraform.

    The K8s API endpoint is configured as private (api_is_public=false) and this is not an ORM deployment.
    Local Terraform cannot reach the K8s API through the NSG rules.

    Solutions:
      1. Set api_is_public = true to allow external access via NSG rules (recommended for initial setup)
      2. Set run_cfgmgt = false and manually apply Helm from a bastion host with VCN access
      3. Use Oracle Resource Manager (ORM) for deployment (has private endpoint access)

    For manual deployment, generated files will be in: cfgmgt/stage/
  EOT

  manual_helm_instructions = <<-EOT
    ⚠️  Helm/kubectl configuration was NOT applied automatically.

    The K8s API endpoint is private and you're running from local Terraform.
    You must apply Helm manually from a machine with VCN access (bastion host or VPN).

    Steps:
      1. Copy the files from cfgmgt/stage/ to your bastion host:
         - kubeconfig
         - helm-values.yaml
         - k8s-manifest.yaml

      2. From the bastion host, run:
         export KUBECONFIG=/path/to/kubeconfig
         kubectl apply -f k8s-manifest.yaml
         helm repo add ai-optimizer https://oracle.github.io/ai-optimizer/helm
         helm upgrade --install ${var.label_prefix} ai-optimizer/ai-optimizer -f helm-values.yaml --version <VERSION>
         (Use --version 0.0.0 for Experimental, omit --version flag for latest Stable release)

      3. Or use the apply.py script:
         python3 apply.py ${var.label_prefix} ${var.label_prefix} --optimizer_version ${var.optimizer_version}

    Note: The K8s API is accessible only from within the VCN due to NSG rules.
  EOT
}

// Repositories
locals {
  optimizer_container_repositories = [
    "ai-optimizer-server",
    "ai-optimizer-client"
  ]
  region_map      = { for r in data.oci_identity_regions.identity_regions.regions : r.name => r.key }
  image_region    = lookup(local.region_map, var.region)
  repository_host = lower(format("%s.ocir.io", local.image_region))
  repository_base = var.byo_ocir_url != "" ? var.byo_ocir_url : lower(format("%s/%s/%s", local.repository_host, data.oci_objectstorage_namespace.objectstorage_namespace.namespace, var.label_prefix))
}

// Cluster Details
locals {
  cluster_name = format("%s-k8s", var.label_prefix)

  // Compute Images
  compute_cpu_arch = (
    can(regex("^VM\\.Standard\\.A[0-9]+\\.Flex$", var.compute_cpu_shape))
    ? "aarch64" : "x86_64"
  )

  oke_worker_images = try({
    for k, v in data.oci_containerengine_node_pool_option.images.sources : v.image_id => merge(
      try(element(regexall("OKE-(?P<version>[0-9\\.]+)-(?P<build>[0-9]+)", v.source_name), 0), { version = "none" }),
      {
        arch        = length(regexall("aarch64", v.source_name)) > 0 ? "aarch64" : "x86_64"
        image_type  = length(regexall("OKE", v.source_name)) > 0 ? "oke" : "platform"
        is_gpu      = length(regexall("GPU", v.source_name)) > 0
        os          = trimspace(replace(element(regexall("^[a-zA-Z-]+", v.source_name), 0), "-", " "))
        os_version  = element(regexall("[0-9\\.]+", v.source_name), 0)
        source_name = v.source_name
      },
    )
  }, {})
  oke_worker_cpu_image = length(local.oke_worker_images) > 0 ? [
    for key, value in local.oke_worker_images : key if
    value["image_type"] == "oke" &&
    value["arch"] == local.compute_cpu_arch &&
    value["os_version"] == var.compute_os_ver &&
    value["version"] == var.kubernetes_version &&
    !value["is_gpu"]
  ][0] : null
  //GPU Data
  oke_worker_gpu_image = length(local.oke_worker_images) > 0 ? [
    for key, value in local.oke_worker_images : key if
    value["image_type"] == "oke" &&
    value["arch"] == "x86_64" &&
    value["os_version"] == var.compute_os_ver &&
    value["version"] == var.kubernetes_version &&
    value["is_gpu"]
  ][0] : null

  // ADs
  gpu_availability_domains = [
    for limit in data.oci_limits_limit_values.gpu_ad_limits.limit_values : limit.availability_domain
    if tonumber(limit.value) > 0
  ]
}