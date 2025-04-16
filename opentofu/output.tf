# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

output "client_url" {
  description = "URL for Client Access"
  value       = format("http://%s", oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address)
}