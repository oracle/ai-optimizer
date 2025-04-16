# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

data "oci_identity_regions" "identity_regions" {}

data "oci_objectstorage_namespace" "objectstorage_namespace" {
  compartment_id = var.compartment_id
}

data "oci_core_vcn" "vcn" {
  vcn_id = var.vcn_id
}

data "oci_load_balancer_load_balancers" "all_lb" {
  compartment_id = var.compartment_id
}

data "oci_limits_limit_values" "gpu_ad_limits" {
  compartment_id = var.tenancy_id
  service_name   = "compute"
  scope_type     = "AD"
  name           = "gpu-a10-count"
}

# https://registry.terraform.io/providers/hashicorp/template/latest/docs/data-sources/cloudinit_config.html
data "cloudinit_config" "workers" {
  gzip          = true
  base64_encode = true

  # Expand root filesystem to fill available space on volume
  part {
    content_type = "text/cloud-config"
    content = jsonencode({
      # https://cloudinit.readthedocs.io/en/latest/reference/modules.html#growpart
      growpart = {
        mode                     = "auto"
        devices                  = ["/"]
        ignore_growroot_disabled = false
      }

      # https://cloudinit.readthedocs.io/en/latest/reference/modules.html#resizefs
      resize_rootfs = true

      # Resize logical LVM root volume when utility is present
      bootcmd = ["if [[ -f /usr/libexec/oci-growfs ]]; then /usr/libexec/oci-growfs -y; fi"]
    })
    filename   = "10-growpart.yml"
    merge_type = "list(append)+dict(no_replace,recurse_list)+str(append)"
  }

  # OKE startup initialization
  part {
    content_type = "text/x-shellscript"
    content      = file("${path.module}/templates/cloudinit-oke.sh")
    filename     = "50-oke.sh"
    merge_type   = "list(append)+dict(no_replace,recurse_list)+str(append)"
  }
}

data "oci_containerengine_cluster_kube_config" "default_cluster_kube_config" {
  cluster_id = oci_containerengine_cluster.default_cluster.id
}

data "oci_containerengine_node_pool_option" "images" {
  node_pool_option_id = oci_containerengine_cluster.default_cluster.id
  compartment_id      = var.compartment_id
}