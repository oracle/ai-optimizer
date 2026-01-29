# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

locals {
  api_endpoint_allowed_cidrs = split(",", replace(var.api_endpoint_allowed_cidrs, "/\\s+/", ""))
  api_endpoint_custom_rules = var.api_is_public ? {
    for allowed_cidr in local.api_endpoint_allowed_cidrs :
    "Allow custom ingress to kube-apiserver from ${allowed_cidr}" => {
      protocol = 6, port = 6443, source = allowed_cidr, source_type = "CIDR_BLOCK"
    }
  } : {}
}

resource "oci_core_network_security_group" "k8s_api_endpoint" {
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = format("%s-k8s-api-endpoint", var.label_prefix)
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}

resource "oci_core_network_security_group" "k8s_workers" {
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = format("%s-k8s-workers", var.label_prefix)
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}

#########################################################################
# Static NSGs - Mess with these at your peril
#########################################################################
locals {
  api_endpoint_default_rules = {
    "K8s API Endpoint from Workers." : {
      protocol = 6, port = 6443,
      source   = data.oci_core_subnet.private.cidr_block, source_type = "CIDR_BLOCK"
    },
    "Control Plane from Workers." : {
      protocol = 6, port = 12250,
      source   = data.oci_core_subnet.private.cidr_block, source_type = "CIDR_BLOCK"
    },
    "K8s API Endpoint Path Discovery - Ingress." : {
      protocol = 1, source = data.oci_core_subnet.private.cidr_block, source_type = "CIDR_BLOCK"
    },
    "Control Plane to K8s Services." : {
      protocol    = 6, port = 443,
      destination = var.oci_services.cidr_block, destination_type = "SERVICE_CIDR_BLOCK"
    },
    "K8s API Endpoint to Workers" : {
      protocol    = 6, port = -1
      destination = data.oci_core_subnet.private.cidr_block, destination_type = "CIDR_BLOCK"
    },
    "K8s API Endpoint Path Discovery - Egress." : {
      protocol = 1, destination = data.oci_core_subnet.private.cidr_block, destination_type = "CIDR_BLOCK"
    },
  }

  workers_default_rules = {
    "Workers from Workers." : {
      protocol = "all", port = -1,
      source   = data.oci_core_subnet.private.cidr_block, source_type = "CIDR_BLOCK"
    },
    "Workers from Load Balancer (Health Checks)." : {
      protocol = 6, port = 10256,
      source   = data.oci_core_subnet.public.cidr_block, source_type = "CIDR_BLOCK"
    },
    "Workers from Load Balancer." : {
      protocol = 6, port_min = 30000, port_max = 32767,
      source   = data.oci_core_subnet.public.cidr_block, source_type = "CIDR_BLOCK"
    },
    "Workers from Control Plane." : {
      protocol = 6, port = -1,
      source   = data.oci_core_subnet.public.cidr_block, source_type = "CIDR_BLOCK"
    },
    "Workers Path Discovery - Ingress." : {
      protocol = 1, source = one(data.oci_core_vcn.vcn.cidr_blocks), source_type = "CIDR_BLOCK"
    },
    "Workers to Workers." : {
      protocol    = "all", port = -1,
      destination = data.oci_core_subnet.private.cidr_block, destination_type = "CIDR_BLOCK"
    },
    "Workers to K8s API Endpoint." : {
      protocol    = 6, port = 6443,
      destination = data.oci_core_subnet.public.cidr_block, destination_type = "CIDR_BLOCK"
    },
    "Workers to Control Plane." : {
      protocol    = 6, port = 12250,
      destination = data.oci_core_subnet.public.cidr_block, destination_type = "CIDR_BLOCK"
    },
    "Workers to K8s Services." : {
      protocol    = 6, port = -1, port_min = 443, port_max = 443,
      destination = var.oci_services.cidr_block, destination_type = "SERVICE_CIDR_BLOCK"
    },
    "Workers to the Internet." : {
      protocol    = 6, port = -1
      destination = "0.0.0.0/0", destination_type = "CIDR_BLOCK"
    },
    "Workers Path Discovery - Egress." : {
      protocol = 1, destination = "0.0.0.0/0", destination_type = "CIDR_BLOCK"
    },
  }
}
#########################################################################
# Implementation
#########################################################################
locals {
  # Dynamic map of all NSG rules for enabled NSGs
  all_rules = { for x, y in merge(
    { for k, v in local.api_endpoint_custom_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.k8s_api_endpoint.id }) },
    { for k, v in local.api_endpoint_default_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.k8s_api_endpoint.id }) },
    { for k, v in local.workers_default_rules : k => merge(v, { "nsg_id" = oci_core_network_security_group.k8s_workers.id }) },
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
    for_each = (tostring(each.value.protocol) == tostring(6) &&
      tonumber(lookup(each.value, "port", 0)) != -1 ? [each.value] : []
    )
    content {
      destination_port_range {
        min = tonumber(lookup(tcp_options.value, "port_min", lookup(tcp_options.value, "port", 0)))
        max = tonumber(lookup(tcp_options.value, "port_max", lookup(tcp_options.value, "port", 0)))
      }
    }
  }

  dynamic "udp_options" {
    for_each = (tostring(each.value.protocol) == tostring(17) &&
      tonumber(lookup(each.value, "port", 0)) != -1 ? [each.value] : []
    )
    content {
      destination_port_range {
        min = tonumber(lookup(udp_options.value, "port_min", lookup(udp_options.value, "port", 0)))
        max = tonumber(lookup(udp_options.value, "port_max", lookup(udp_options.value, "port", 0)))
      }
    }
  }

  dynamic "icmp_options" {
    for_each = tostring(each.value.protocol) == tostring(1) ? [1] : []
    content {
      type = 3
      code = 4
    }
  }
}