# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// Region Mapping
locals {
  identity_tag_key = format("%s.%s", oci_identity_tag_namespace.tag_namespace.name, oci_identity_tag.identity_tag.name)
  identity_tag_val = var.label_prefix
  region_map = {
    for r in data.oci_identity_regions.identity_regions.regions : r.name => r.key
  }
  image_region = lookup(
    local.region_map,
    var.region
  )
  // Load Balancer
  lb = [
    for lb in data.oci_load_balancer_load_balancers.all_lb.load_balancers : lb
    if lb.id == var.lb_id
  ]

  server_repository = lower(format("%s.ocir.io/%s/%s", local.image_region, data.oci_objectstorage_namespace.objectstorage_namespace.namespace, oci_artifacts_container_repository.server_repository.display_name))
  client_repository = lower(format("%s.ocir.io/%s/%s", local.image_region, data.oci_objectstorage_namespace.objectstorage_namespace.namespace, oci_artifacts_container_repository.explorer_repository.display_name))
  k8s_cluster_name  = format("%s-k8s", var.label_prefix)
  helm_values = templatefile("${path.module}/templates/helm_values.yaml", {
    label                    = var.label_prefix
    server_repository        = local.server_repository
    client_repository        = local.client_repository
    oci_region               = var.region
    adb_ocid                 = var.adb_id
    adb_name                 = var.adb_name
    k8s_node_pool_gpu_deploy = var.k8s_node_pool_gpu_deploy
    lb_ip                    = local.lb[0].ip_address_details[0].ip_address
  })

  k8s_manifest = templatefile("${path.module}/templates/k8s_manifest.yaml", {
    label            = var.label_prefix
    compartment_ocid = local.lb[0].compartment_id
    lb_ocid          = local.lb[0].id
    lb_subnet_ocid   = var.public_subnet_id
    lb_ip_ocid       = local.lb[0].ip_address_details[0].ip_address
    lb_nsgs          = var.lb_nsg_id
    lb_min_shape     = local.lb[0].shape_details[0].minimum_bandwidth_in_mbps
    lb_max_shape     = local.lb[0].shape_details[0].maximum_bandwidth_in_mbps
    adb_name         = var.adb_name
    adb_password     = var.adb_password
    adb_service      = format("%s_TP", var.adb_name)
    api_key          = random_string.api_key.result
  })

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
    value["arch"] == "x86_64" &&
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