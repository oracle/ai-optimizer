output "ip" {
  value = oci_core_instance.instance["VM"].public_ip
}