// Worker Node Pool
resource "oci_core_network_security_group" "workers" {
  compartment_id = local.compartment_ocid
  vcn_id         = module.network.vcn_ocid
  display_name   = format("%s-workers", local.label_prefix)
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}