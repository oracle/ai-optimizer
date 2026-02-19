# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

// Housekeeping
locals {
  compartment_ocid = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  label_prefix     = var.label_prefix != "" ? substr(lower(var.label_prefix), 0, 12) : substr(lower(random_pet.label.id), 0, 12)
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
  vcn_ocid                  = var.byo_vcn_ocid == "" ? module.network["managed"].vcn_ocid : var.byo_vcn_ocid
  public_subnet_ocid        = var.byo_vcn_ocid == "" ? module.network["managed"].public_subnet_ocid : var.byo_public_subnet_ocid
  private_subnet_ocid       = var.byo_vcn_ocid == "" ? module.network["managed"].private_subnet_ocid : var.byo_private_subnet_ocid
  private_subnet_cidr_block = var.byo_vcn_ocid == "" ? module.network["managed"].private_subnet_cidr_block : data.oci_core_subnet.byo_vcn_private[0].cidr_block
}

// Database
locals {
  db_ocid = (
    var.byo_db_type == "" ? oci_database_autonomous_database.default_adb["managed"].id :
    var.byo_db_type == "ADB-S" ? data.oci_database_autonomous_database.byo_adb["byo"].id :
    "N/A"
  )

  db_name = (
    var.byo_db_type == "" ? upper(format("%sDB", local.label_prefix)) :
    var.byo_db_type == "ADB-S" ? data.oci_database_autonomous_database.byo_adb["byo"].db_name :
    var.byo_odb_service
  )

  db_conn = {
    db_type  = var.byo_db_type == "OTHER" ? "OTHER" : "ADB"
    username = var.byo_db_type == "OTHER" ? "SYSTEM" : "ADMIN"
    password = (
      var.byo_db_type == "" ? format("%s%s", random_password.adb_char[0].result, random_password.adb_rest[0].result) :
      var.byo_db_password
    )
    service = (
      var.byo_db_type == "OTHER" ? format("%s:%s/%s", var.byo_odb_host, var.byo_odb_port, var.byo_odb_service) :
      format("%s_TP", local.db_name)
    )
  }

  adb_whitelist_cidrs = (
    var.adb_networking == "PRIVATE_ENDPOINT_ACCESS" ? null :
    concat(
      var.adb_whitelist_cidrs != "" ? split(",", replace(var.adb_whitelist_cidrs, "/\\s+/", "")) : [],
      [local.vcn_ocid]
    )
  )
  adb_nsg                    = var.byo_vcn_ocid != "" && var.adb_networking == "PRIVATE_ENDPOINT_ACCESS" ? [oci_core_network_security_group.adb[0].id] : []
  adb_subnet_id              = var.adb_networking == "PRIVATE_ENDPOINT_ACCESS" ? local.private_subnet_ocid : null
  adb_private_endpoint_label = var.adb_networking == "PRIVATE_ENDPOINT_ACCESS" ? local.label_prefix : null
}

// Load Balancer Ports
locals {
  lb_http_port  = 80
  lb_https_port = 443
}