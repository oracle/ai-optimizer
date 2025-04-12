# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

// random
resource "random_pet" "label" {
  length = 1
}

resource "random_password" "adb_char" {
  length  = 2
  special = false
  numeric = false
}

resource "random_password" "adb_rest" {
  length           = 14
  min_numeric      = 2
  min_lower        = 2
  min_upper        = 2
  min_special      = 2
  override_special = "!$%^*-_"
  keepers = {
    uuid = "uuid()"
  }
}

// Load Balancer
resource "oci_load_balancer" "lb" {
  compartment_id = local.compartment_ocid
  display_name   = format("%s-lb", local.label_prefix)
  shape          = "flexible"
  is_private     = false
  shape_details {
    minimum_bandwidth_in_mbps = var.lb_min_shape
    maximum_bandwidth_in_mbps = var.lb_max_shape
  }
  subnet_ids = [
    module.network.public_subnet_ocid
  ]
  network_security_group_ids = [
    oci_core_network_security_group.client_lb.id,
    oci_core_network_security_group.server_lb.id
  ]
}

resource "oci_load_balancer_backend_set" "client_lb_backend_set" {
  for_each         = var.infrastructure == "VM" ? { "VM" = "VM" } : {}
  load_balancer_id = oci_load_balancer.lb.id
  name             = format("%s-client-lb-backend-set", local.label_prefix)
  policy           = "LEAST_CONNECTIONS"
  health_checker {
    port     = local.streamlit_port
    protocol = "HTTP"
    url_path = "/_stcore/health"
  }
}

resource "oci_load_balancer_backend_set" "server_lb_backend_set" {
  for_each         = var.infrastructure == "VM" ? { "VM" = "VM" } : {}
  load_balancer_id = oci_load_balancer.lb.id
  name             = format("%s-server-lb-backend-set", local.label_prefix)
  policy           = "LEAST_CONNECTIONS"
  health_checker {
    port     = local.fast_apiserver_port
    protocol = "HTTP"
    url_path = "/v1/liveness"
  }
}

resource "oci_load_balancer_listener" "client_lb_listener" {
  for_each                 = var.infrastructure == "VM" ? { "VM" = "VM" } : {}
  load_balancer_id         = oci_load_balancer.lb.id
  name                     = format("%s-client-lb-listener", local.label_prefix)
  default_backend_set_name = oci_load_balancer_backend_set.client_lb_backend_set["VM"].name
  port                     = local.client_lb_port
  protocol                 = "HTTP"
}

resource "oci_load_balancer_listener" "server_lb_listener" {
  for_each                 = var.infrastructure == "VM" ? { "VM" = "VM" } : {}
  load_balancer_id         = oci_load_balancer.lb.id
  name                     = format("%s-server-lb-listener", local.label_prefix)
  default_backend_set_name = oci_load_balancer_backend_set.server_lb_backend_set["VM"].name
  port                     = local.server_lb_port
  protocol                 = "HTTP"
}

resource "oci_load_balancer_backend" "client_lb_backend" {
  for_each         = var.infrastructure == "VM" ? { "VM" = "VM" } : {}
  load_balancer_id = oci_load_balancer.lb.id
  backendset_name  = oci_load_balancer_backend_set.client_lb_backend_set["VM"].name
  ip_address       = oci_core_instance.instance["VM"].private_ip
  port             = local.streamlit_port
}

resource "oci_load_balancer_backend" "server_lb_backend" {
  for_each         = var.infrastructure == "VM" ? { "VM" = "VM" } : {}
  load_balancer_id = oci_load_balancer.lb.id
  backendset_name  = oci_load_balancer_backend_set.server_lb_backend_set["VM"].name
  ip_address       = oci_core_instance.instance["VM"].private_ip
  port             = local.fast_apiserver_port
}

// Autonomous Database
resource "oci_database_autonomous_database" "default_adb" {
  admin_password                       = local.adb_password
  autonomous_maintenance_schedule_type = "REGULAR"
  character_set                        = "AL32UTF8"
  compartment_id                       = local.compartment_ocid
  compute_count                        = var.adb_ecpu_core_count
  compute_model                        = "ECPU"
  data_storage_size_in_gb              = var.adb_data_storage_size_in_gb
  database_edition                     = var.adb_license_model == "BRING_YOUR_OWN_LICENSE" ? var.adb_edition : null
  db_name                              = local.adb_name
  db_version                           = var.adb_version
  db_workload                          = "OLTP"
  display_name                         = local.adb_name
  is_free_tier                         = false
  is_auto_scaling_enabled              = var.adb_is_cpu_auto_scaling_enabled
  is_auto_scaling_for_storage_enabled  = var.adb_is_storage_auto_scaling_enabled
  is_dedicated                         = false
  license_model                        = var.adb_license_model
  is_mtls_connection_required          = true
  whitelisted_ips                      = local.adb_whitelist_cidrs
}

// VM Infrastructure
resource "oci_core_instance" "instance" {
  for_each            = var.infrastructure == "VM" ? { "VM" = "VM" } : {}
  compartment_id      = local.compartment_ocid
  display_name        = format("%s-compute", local.label_prefix)
  availability_domain = local.availability_domains[0]
  shape               = var.compute_cpu_shape
  shape_config {
    memory_in_gbs = var.compute_cpu_ocpu * 16
    ocpus         = var.compute_cpu_ocpu
  }
  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.images["VM"].images[0].id
    boot_volume_size_in_gbs = 50
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
    subnet_id        = module.network.private_subnet_ocid
    assign_public_ip = false
    nsg_ids          = [oci_core_network_security_group.compute["VM"].id]
  }
  defined_tags = { (local.identity_tag_key) = local.identity_tag_val }
  metadata = {
    user_data = "${base64encode(local.cloud_init)}"
  }
  lifecycle {
    create_before_destroy = true
    ignore_changes        = [source_details.0.source_id, defined_tags]
  }
}