# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// House-Keeping
locals {
  compartment_ocid = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  label_prefix     = var.label_prefix != "" ? lower(var.label_prefix) : lower(random_pet.label.id)
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

locals {
  cloud_init = templatefile("templates/cloudinit-compute.tpl", {
    compartment_id = local.compartment_ocid
    db_password    = local.adb_password
    db_name        = local.adb_name
    oci_region     = var.region
    source_code    = var.source_repository
    tenancy_id = var.tenancy_ocid
  })
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