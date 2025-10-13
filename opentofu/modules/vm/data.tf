# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable



data "oci_core_images" "images" {
  compartment_id   = var.compartment_id
  operating_system = "Oracle Linux"
  shape            = local.vm_compute_shape

  filter {
    name = "display_name"
    values = [
      var.vm_is_gpu_shape ? "Oracle-Linux-${var.compute_os_ver}-.*(GPU|NVIDIA|A10).*" : "Oracle-Linux-${var.compute_os_ver}-.*"
    ]
    regex = true
  }

  sort_by    = "TIMECREATED"
  sort_order = "DESC"
}

data "oci_core_vcn" "vcn" {
  vcn_id = var.vcn_id
}

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

  # Custom Startup Initialisation (compute and database)
  part {
    content_type = "text/x-shellscript"
    content      = local.cloud_init_compute
    filename     = "50-custom-compute-init.sh"
    merge_type   = "list(append)+dict(no_replace,recurse_list)+str(append)"
  }
  part {
    content_type = "text/x-shellscript"
    content      = local.cloud_init_database
    filename     = "50-custom-database-init.sh"
    merge_type   = "list(append)+dict(no_replace,recurse_list)+str(append)"
  }
}