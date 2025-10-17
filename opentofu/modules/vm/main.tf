# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// Loadbalancer
resource "oci_load_balancer_backend_set" "client_lb_backend_set" {
  load_balancer_id = var.lb_id
  name             = format("%s-client-lbbs", var.label_prefix)
  policy           = "LEAST_CONNECTIONS"
  health_checker {
    port     = local.streamlit_client_port
    protocol = "HTTP"
    url_path = "/_stcore/health"
  }
}

resource "oci_load_balancer_backend_set" "server_lb_backend_set" {
  load_balancer_id = var.lb_id
  name             = format("%s-server-lbbs", var.label_prefix)
  policy           = "LEAST_CONNECTIONS"
  health_checker {
    port     = local.fastapi_server_port
    protocol = "HTTP"
    url_path = "/v1/liveness"
  }
}

resource "oci_load_balancer_listener" "client_lb_listener" {
  load_balancer_id         = var.lb_id
  name                     = format("%s-client-lb-listener", var.label_prefix)
  default_backend_set_name = oci_load_balancer_backend_set.client_lb_backend_set.name
  port                     = var.lb_client_port
  protocol                 = "HTTP"
}

resource "oci_load_balancer_listener" "server_lb_listener" {
  load_balancer_id         = var.lb_id
  name                     = format("%s-server-lb-listener", var.label_prefix)
  default_backend_set_name = oci_load_balancer_backend_set.server_lb_backend_set.name
  port                     = var.lb_server_port
  protocol                 = "HTTP"
}

resource "oci_load_balancer_backend" "client_lb_backend" {
  load_balancer_id = var.lb_id
  backendset_name  = oci_load_balancer_backend_set.client_lb_backend_set.name
  ip_address       = oci_core_instance.instance.private_ip
  port             = local.streamlit_client_port
}

resource "oci_load_balancer_backend" "server_lb_backend" {
  load_balancer_id = var.lb_id
  backendset_name  = oci_load_balancer_backend_set.server_lb_backend_set.name
  ip_address       = oci_core_instance.instance.private_ip
  port             = local.fastapi_server_port
}

// Compute Instance
resource "oci_core_instance" "instance" {
  compartment_id      = var.compartment_id
  display_name        = format("%s-compute", var.label_prefix)
  availability_domain = var.availability_domains[0]
  shape               = local.vm_compute_shape
  dynamic "shape_config" {
    for_each = var.vm_is_gpu_shape ? [] : [1]
    content {
      memory_in_gbs = var.compute_cpu_ocpu * 16
      ocpus         = var.compute_cpu_ocpu
    }
  }
  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.images.images[0].id
    boot_volume_size_in_gbs = 100
  }
  agent_config {
    are_all_plugins_disabled = false
    is_management_disabled   = false
    is_monitoring_disabled   = false
    plugins_config {
      desired_state = "ENABLED"
      name          = "Bastion"
    }
  }
  create_vnic_details {
    subnet_id        = var.private_subnet_id
    assign_public_ip = false
    nsg_ids          = [oci_core_network_security_group.compute.id]
  }
  metadata = {
    user_data = data.cloudinit_config.workers.rendered
  }
  lifecycle {
    create_before_destroy = true
    ignore_changes        = [source_details.0.source_id, defined_tags]
  }
}