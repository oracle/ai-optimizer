output "client_url" {
  description = "URL for Client Access"
  value       = format("http://%s", oci_core_instance.instance["VM"].public_ip)
}