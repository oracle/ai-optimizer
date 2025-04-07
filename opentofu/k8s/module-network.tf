# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

module "network" {
  source         = "./modules/network"
  compartment_id = local.compartment_ocid
  label_prefix   = local.label_prefix
}