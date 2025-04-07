# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

#########################################################################
# Variable NSGs
#########################################################################
locals {
  k8s_api_endpoint_allowed_cidrs      = split(",", replace(var.k8s_api_endpoint_allowed_cidrs, "/\\s+/", ""))
  service_lb_allowed_app_client_cidrs = split(",", replace(var.service_lb_allowed_app_client_cidrs, "/\\s+/", ""))
  service_lb_allowed_app_client_port  = split(",", replace(var.service_lb_allowed_app_client_port, "/\\s+/", ""))
  service_lb_allowed_app_server_cidrs = split(",", replace(var.service_lb_allowed_app_server_cidrs, "/\\s+/", ""))
  service_lb_allowed_app_server_port  = split(",", replace(var.service_lb_allowed_app_server_port, "/\\s+/", ""))
}

locals {
  k8s_api_endpoint_cidr_rules = var.k8s_api_is_public ? {
    for allowed_cidr in local.k8s_api_endpoint_allowed_cidrs :
    "Allow custom ingress to kube-apiserver from ${allowed_cidr}" => {
      protocol = local.tcp_protocol, port = local.apiserver_port, source = allowed_cidr, source_type = local.rule_type_cidr
    }
  } : {}

  service_lb_app_client_rules = flatten([for cidr in local.service_lb_allowed_app_client_cidrs : [
    for port in local.service_lb_allowed_app_client_port :
    { cidr = cidr, port = port }]
  ])
  service_lb_app_server_rules = flatten([for cidr in local.service_lb_allowed_app_server_cidrs : [
    for port in local.service_lb_allowed_app_server_port :
    { cidr = cidr, port = port }]
  ])

  service_lb_cidr_port_app_client_rules = var.service_lb_is_public ? {
    for rule in local.service_lb_app_client_rules :
    "Allow custom ingress to Load Balancer HTTP port ${rule.port} from ${rule.cidr}" => {
      protocol = local.tcp_protocol, port = rule.port, source = rule.cidr, source_type = local.rule_type_cidr
    }
  } : {}
  service_lb_cidr_port_app_server_rules = var.service_lb_is_public ? {
    for rule in local.service_lb_app_server_rules :
    "Allow custom ingress to Load Balancer API port ${rule.port} from ${rule.cidr}" => {
      protocol = local.tcp_protocol, port = rule.port, source = rule.cidr, source_type = local.rule_type_cidr
    }
  } : {}
}

#########################################################################
# Static NSGs - Mess with these at your peril
#########################################################################
locals {
  k8s_api_endpoint_default_rules = {
    "K8s API Endpoint from Workers." : {
      protocol = local.tcp_protocol, port = local.apiserver_port,
      source   = module.network.private_subnet_cidr_block, source_type = local.rule_type_cidr
    },
    "Control Plane from Workers." : {
      protocol = local.tcp_protocol, port = local.control_plane_port,
      source   = module.network.private_subnet_cidr_block, source_type = local.rule_type_cidr
    },
    "K8s API Endpoint Path Discovery - Ingress." : {
      protocol = local.icmp_protocol, source = module.network.private_subnet_cidr_block, source_type = local.rule_type_cidr
    },
    "Control Plane to K8s Services." : {
      protocol    = local.tcp_protocol, port = 443,
      destination = data.oci_core_services.core_services.services.0.cidr_block, destination_type = local.rule_type_service
    },
    "K8s API Endpoint to Workers" : {
      protocol    = local.tcp_protocol, port = local.all_ports
      destination = module.network.private_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
    "K8s API Endpoint Path Discovery - Egress." : {
      protocol = local.icmp_protocol, destination = module.network.private_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
  }

  k8s_workers_default_rules = {
    "Workers from Workers." : {
      protocol = local.all_protocols, port = local.all_ports,
      source   = module.network.private_subnet_cidr_block, source_type = local.rule_type_cidr
    },
    "Workers from Load Balancer (Health Checks)." : {
      protocol = local.tcp_protocol, port = local.health_check_port,
      source   = module.network.public_subnet_cidr_block, source_type = local.rule_type_cidr
    },
    "Workers from Load Balancer." : {
      protocol = local.tcp_protocol, port_min = local.node_port_min, port_max = local.node_port_max,
      source   = module.network.public_subnet_cidr_block, source_type = local.rule_type_cidr
    },
    "Workers from Control Plane." : {
      protocol = local.tcp_protocol, port = local.all_ports,
      source   = module.network.public_subnet_cidr_block, source_type = local.rule_type_cidr
    },
    "Workers Path Discovery - Ingress." : {
      protocol = local.icmp_protocol, source = module.network.vcn_cidr_block, source_type = local.rule_type_cidr
    },
    "Workers to Workers." : {
      protocol    = local.all_protocols, port = local.all_ports,
      destination = module.network.private_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
    "Workers to K8s API Endpoint." : {
      protocol    = local.tcp_protocol, port = local.apiserver_port,
      destination = module.network.public_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
    "Workers to Control Plane." : {
      protocol    = local.tcp_protocol, port = local.control_plane_port,
      destination = module.network.public_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
    "Workers to K8s Services." : {
      protocol    = local.tcp_protocol, port = local.all_ports, port_min = 443, port_max = 443,
      destination = data.oci_core_services.core_services.services.0.cidr_block, destination_type = local.rule_type_service
    },
    "Workers to the Internet." : {
      protocol    = local.tcp_protocol, port = local.all_ports
      destination = local.anywhere, destination_type = local.rule_type_cidr
    },
    "Workers Path Discovery - Egress." : {
      protocol = local.icmp_protocol, destination = local.anywhere, destination_type = local.rule_type_cidr
    },
  }

  service_lb_default_app_client_rules = var.service_lb_is_public ? {
    "Load Balancer HTTP from Workers (Health Checks)." : {
      protocol    = local.tcp_protocol, port = local.health_check_port,
      destination = module.network.private_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
    "Load Balancer HTTP from Workers." : {
      protocol    = local.tcp_protocol, port_min = local.node_port_min, port_max = local.node_port_max,
      destination = module.network.private_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
  } : {}

  service_lb_default_app_server_rules = var.service_lb_is_public ? {
    "Load Balancer API from Workers (Health Checks)." : {
      protocol    = local.tcp_protocol, port = local.health_check_port,
      destination = module.network.private_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
    "Load Balancer API from Workers." : {
      protocol    = local.tcp_protocol, port_min = local.node_port_min, port_max = local.node_port_max,
      destination = module.network.private_subnet_cidr_block, destination_type = local.rule_type_cidr
    },
  } : {}
}

#########################################################################
# Helpers
#########################################################################
locals {
  # Dynamic map of all NSG rules for enabled NSGs
  all_rules = { for x, y in merge(
    { for k, v in local.k8s_api_endpoint_default_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.k8s_api_endpoint.id }) },
    { for k, v in local.k8s_api_endpoint_cidr_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.k8s_api_endpoint.id }) },
    { for k, v in local.k8s_workers_default_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.k8s_workers.id }) },
    { for k, v in local.service_lb_default_app_client_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.service_lb_app_client[0].id }) },
    { for k, v in local.service_lb_cidr_port_app_client_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.service_lb_app_client[0].id }) },
    { for k, v in local.service_lb_default_app_server_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.service_lb_app_server[0].id }) },
    { for k, v in local.service_lb_cidr_port_app_server_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.service_lb_app_server[0].id }) },
    ) : x => merge(y, {
      description               = x
      network_security_group_id = lookup(y, "nsg_id")
      direction                 = contains(keys(y), "source") ? "INGRESS" : "EGRESS"
      protocol                  = lookup(y, "protocol")
      source                    = lookup(y, "source", null)
      source_type               = lookup(y, "source_type", null)
      destination               = lookup(y, "destination", null)
      destination_type          = lookup(y, "destination_type", null)
  }) }
}

#########################################################################
# Implement
#########################################################################
resource "oci_core_network_security_group_security_rule" "k8s" {
  for_each                  = local.all_rules
  stateless                 = false
  description               = each.value.description
  destination               = each.value.destination
  destination_type          = each.value.destination_type
  direction                 = each.value.direction
  network_security_group_id = each.value.network_security_group_id
  protocol                  = each.value.protocol
  source                    = each.value.source
  source_type               = each.value.source_type

  dynamic "tcp_options" {
    for_each = (tostring(each.value.protocol) == tostring(local.tcp_protocol) &&
      tonumber(lookup(each.value, "port", 0)) != local.all_ports ? [each.value] : []
    )
    content {
      destination_port_range {
        min = tonumber(lookup(tcp_options.value, "port_min", lookup(tcp_options.value, "port", 0)))
        max = tonumber(lookup(tcp_options.value, "port_max", lookup(tcp_options.value, "port", 0)))
      }
    }
  }

  dynamic "udp_options" {
    for_each = (tostring(each.value.protocol) == tostring(local.udp_protocol) &&
      tonumber(lookup(each.value, "port", 0)) != local.all_ports ? [each.value] : []
    )
    content {
      destination_port_range {
        min = tonumber(lookup(udp_options.value, "port_min", lookup(udp_options.value, "port", 0)))
        max = tonumber(lookup(udp_options.value, "port_max", lookup(udp_options.value, "port", 0)))
      }
    }
  }

  dynamic "icmp_options" {
    for_each = tostring(each.value.protocol) == tostring(local.icmp_protocol) ? [1] : []
    content {
      type = 3
      code = 4
    }
  }

  lifecycle {
    precondition {
      condition = tostring(each.value.protocol) == tostring(local.icmp_protocol) || contains(keys(each.value), "port") || (
        contains(keys(each.value), "port_min") && contains(keys(each.value), "port_max")
      )
      error_message = "TCP/UDP rule must contain a port or port range: '${each.key}'"
    }

    precondition {
      condition = (
        tostring(each.value.protocol) == tostring(local.icmp_protocol)
        || can(tonumber(each.value.port))
        || (can(tonumber(each.value.port_min)) && can(tonumber(each.value.port_max)))
      )

      error_message = "TCP/UDP ports must be numeric: '${each.key}'"
    }

    precondition {
      condition     = each.value.direction == "EGRESS" || coalesce(each.value.source, "none") != "none"
      error_message = "Ingress rule must have a source: '${each.key}'"
    }

    precondition {
      condition     = each.value.direction == "INGRESS" || coalesce(each.value.destination, "none") != "none"
      error_message = "Egress rule must have a destination: '${each.key}'"
    }
  }
}