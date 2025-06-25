# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// Housekeeping
locals {
  compartment_ocid = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  label_prefix     = var.label_prefix != "" ? lower(var.label_prefix) : lower(random_pet.label.id)
}

// Autonomous Database
locals {
  adb_name = format("%sDB", upper(local.label_prefix))
  adb_whitelist_cidrs = concat(
    var.adb_whitelist_cidrs != "" ? split(",", replace(var.adb_whitelist_cidrs, "/\\s+/", "")) : [],
    [module.network.vcn_ocid]
  )
  adb_password = sensitive(format("%s%s", random_password.adb_char.result, random_password.adb_rest.result))
}

// Availability Domains
locals {
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

// Network
locals {
  streamlit_client_port = 8501
  fastapi_server_port   = 8000
  lb_client_port        = 80
  lb_server_port        = 8000
}