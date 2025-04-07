# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.27" // Last evaluated 21-Feb-2025
    }
  }
  required_version = ">= 1.5"
}

data "oci_identity_region_subscriptions" "home_region" {
  tenancy_id = var.tenancy_ocid
  filter {
    name   = "is_home_region"
    values = ["true"]
  }
}

locals {
  home_region = data.oci_identity_region_subscriptions.home_region.region_subscriptions[0].region_name
  user_ocid   = var.user_ocid != "" ? var.user_ocid : var.current_user_ocid
}

provider "oci" {
  region           = var.region
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = local.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  private_key      = var.private_key
}

provider "oci" {
  region           = local.home_region
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = local.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  private_key      = var.private_key
  alias            = "home_region"
}
