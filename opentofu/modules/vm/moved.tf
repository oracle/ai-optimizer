# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

// 2.1.0 → 2.1.1: client/server LB listeners were split. Preserve state across the rename
// so existing deployments don't hit "Default Listener on port '443' refer to VIP 'public-vip' twice".
moved {
  from = oci_load_balancer_listener.https_lb_listener
  to   = oci_load_balancer_listener.client_https_lb_listener[0]
}

moved {
  from = oci_load_balancer_listener.client_https_lb_listener[0]
  to   = oci_load_balancer_listener.client_https_lb_listener
}

moved {
  from = oci_load_balancer_listener.server_https_lb_listener[0]
  to   = oci_load_balancer_listener.server_https_lb_listener
}
