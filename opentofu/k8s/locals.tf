# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// House-Keeping
locals {
  compartment_ocid  = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  label_prefix      = var.label_prefix != "" ? lower(var.label_prefix) : lower(random_pet.label.id)
  k8s_cluster_name  = format("%s-k8s", local.label_prefix)
  server_repository = lower(format("%s.ocir.io/%s/%s", local.image_region, data.oci_objectstorage_namespace.objectstorage_namespace.namespace, oci_artifacts_container_repository.server_repository.display_name))
  client_repository = lower(format("%s.ocir.io/%s/%s", local.image_region, data.oci_objectstorage_namespace.objectstorage_namespace.namespace, oci_artifacts_container_repository.explorer_repository.display_name))
  identity_tag_key  = format("%s.%s", oci_identity_tag_namespace.tag_namespace.name, oci_identity_tag.identity_tag.name)
  identity_tag_val  = local.k8s_cluster_name
}

// ADs
locals {
  // Tenancy-specific availability domains in region
  ads = data.oci_identity_availability_domains.all.availability_domains

  // Map of parsed availability domain numbers to tenancy-specific names
  // Used by resources with AD placement for generic selection
  ad_numbers_to_names = local.ads != null ? {
    for ad in local.ads : parseint(substr(ad.name, -1, -1), 10) => ad.name
  } : { -1 : "" } # Fallback handles failure when unavailable but not required

  // List of availability domain numbers in region
  // Used to intersect desired AD lists against presence in region
  ad_numbers = local.ads != null ? sort(keys(local.ad_numbers_to_names)) : []

  availability_domains = compact([for ad_number in tolist(local.ad_numbers) :
    lookup(local.ad_numbers_to_names, ad_number, null)
  ])
}

// OKE Images
locals {
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
  oke_worker_cpu_image = [for key, value in local.oke_worker_images : key if
  value["image_type"] == "oke" && value["arch"] == "x86_64" && value["os_version"] == var.k8s_worker_os_ver && value["k8s_version"] == var.k8s_version && !value["is_gpu"]][0]

  //GPU Data
  oke_worker_gpu_image = [for key, value in local.oke_worker_images : key if
  value["image_type"] == "oke" && value["arch"] == "x86_64" && value["os_version"] == var.k8s_worker_os_ver && value["k8s_version"] == var.k8s_version && value["is_gpu"]][0]
  // ADs
  gpu_availability_domains = [
    for limit in data.oci_limits_limit_values.gpu_ad_limits.limit_values : limit.availability_domain
    if tonumber(limit.value) > 0
  ]
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
}

locals {
  # Port numbers
  all_ports          = -1
  apiserver_port     = 6443
  health_check_port  = 10256
  control_plane_port = 12250
  node_port_min      = 30000
  node_port_max      = 32767

  # Protocols
  # See https://www.iana.org/assignments/protocol-numbers/protocol-numbers.xhtml
  all_protocols = "all"
  icmp_protocol = 1
  tcp_protocol  = 6
  udp_protocol  = 17

  anywhere          = "0.0.0.0/0"
  rule_type_nsg     = "NETWORK_SECURITY_GROUP"
  rule_type_cidr    = "CIDR_BLOCK"
  rule_type_service = "SERVICE_CIDR_BLOCK"
}

// Worker Nodes
locals {
  instance_ids = flatten(concat(
    data.oci_containerengine_node_pool.default_node_pool_details.nodes[*].id,
    var.k8s_node_pool_gpu_deploy ? data.oci_containerengine_node_pool.gpu_node_pool_details[*].nodes[*].id : []
  ))
}