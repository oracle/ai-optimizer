data "oci_core_images" "images" {
  compartment_id   = local.compartment_ocid
  operating_system = "Oracle Linux"
  shape            = var.worker_cpu_shape

  filter {
    name   = "display_name"
    values = ["Oracle-Linux-${var.worker_os_ver}-.*"]
    regex  = true
  }

  sort_by    = "TIMECREATED"
  sort_order = "DESC"
}

// oci_identity
data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

