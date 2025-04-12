output "client_url" {
  description = "URL for Client Access"
  value       = format("http://%s", oci_load_balancer.lb.ip_address_details[0].ip_address)
}