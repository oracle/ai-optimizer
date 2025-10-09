# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// Oracle Resource Manager
locals {
  create_orm_pe = var.orm_install && !var.k8s_api_is_public
}

// Region Mapping
locals {
  region_map = {
    for r in data.oci_identity_regions.identity_regions.regions : r.name => r.key
  }
  image_region = lookup(
    local.region_map,
    var.region
  )
  repository_host   = lower(format("%s.ocir.io", local.image_region))
  repository_server = lower(format("%s/%s/%s", local.repository_host, data.oci_objectstorage_namespace.objectstorage_namespace.namespace, oci_artifacts_container_repository.repository_server.display_name))
  repository_client = lower(format("%s/%s/%s", local.repository_host, data.oci_objectstorage_namespace.objectstorage_namespace.namespace, oci_artifacts_container_repository.repository_client.display_name))
  k8s_cluster_name  = format("%s-k8s", var.label_prefix)

  oke_worker_images = try({
    for k, v in data.oci_containerengine_node_pool_option.images.sources : v.image_id => merge(
      try(element(regexall("OKE-(?P<k8s_version>[0-9\\.]+)-(?P<build>[0-9]+)", v.source_name), 0), { k8s_version = "none" }),
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
    value["arch"] == var.compute_cpu_arch &&
    value["os_version"] == var.compute_os_ver &&
    value["k8s_version"] == var.k8s_version &&
    !value["is_gpu"]
  ][0] : null
  //GPU Data
  oke_worker_gpu_image = length(local.oke_worker_images) > 0 ? [
    for key, value in local.oke_worker_images : key if
    value["image_type"] == "oke" &&
    value["arch"] == "x86_64" &&
    value["os_version"] == var.compute_os_ver &&
    value["k8s_version"] == var.k8s_version &&
    value["is_gpu"]
  ][0] : null
  // ADs
  gpu_availability_domains = [
    for limit in data.oci_limits_limit_values.gpu_ad_limits.limit_values : limit.availability_domain
    if tonumber(limit.value) > 0
  ]
}