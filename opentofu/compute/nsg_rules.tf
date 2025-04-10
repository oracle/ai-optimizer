# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

#########################################################################
# Static NSGs - Mess with these at your peril
#########################################################################
locals {
  workers_default_rules = {
    "Workers Web Access - Ingress." : {
      protocol = local.tcp_protocol, port = 8501
      source   = local.anywhere, source_type = local.rule_type_cidr
    },
    "Workers Path Discovery - Ingress." : {
      protocol = local.icmp_protocol, source = module.network.vcn_cidr_block, source_type = local.rule_type_cidr
    },
    "Workers to the Internet - Egress." : {
      protocol    = local.tcp_protocol, port = local.all_ports
      destination = local.anywhere, destination_type = local.rule_type_cidr
    },
    "Workers Path Discovery - Egress." : {
      protocol = local.icmp_protocol, destination = local.anywhere, destination_type = local.rule_type_cidr
    },
  }
}

#########################################################################
# Helpers
#########################################################################
locals {
  # Dynamic map of all NSG rules for enabled NSGs
  all_rules = { for x, y in merge(
    { for k, v in local.workers_default_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.workers.id }) },
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