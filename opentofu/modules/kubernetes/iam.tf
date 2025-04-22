# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

resource "oci_identity_tag_namespace" "tag_namespace" {
  compartment_id = var.compartment_id
  description    = format("%s Tag Namespace", var.label_prefix)
  name           = var.label_prefix
  provider       = oci.home_region
}

resource "oci_identity_tag" "identity_tag" {
  description      = format("%s Infrastructure", var.label_prefix)
  name             = "infrastructure"
  tag_namespace_id = oci_identity_tag_namespace.tag_namespace.id
  provider         = oci.home_region
}

resource "oci_identity_dynamic_group" "node_dynamic_group" {
  compartment_id = var.tenancy_id
  name           = format("%s-workers-dyngrp", var.label_prefix)
  description    = format("%s Dynamic Group - K8s Workers", var.label_prefix)
  matching_rule = format(
    "All {instance.compartment.id = '%s', tag.%s.value = '%s'}",
    var.compartment_id, local.identity_tag_key, local.identity_tag_val
  )
  provider = oci.home_region
}

resource "oci_identity_policy" "workload_node_policies" {
  compartment_id = var.tenancy_id
  name           = format("%s-worker-workload-policy", var.label_prefix)
  description    = format("%s PrincipleAuth - K8s Workers", var.label_prefix)
  statements = [
    format("allow any-user to manage autonomous-database-family in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'oracle-database-operator-system', request.principal.service_account = 'default', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to read objectstorage-namespaces in compartment id %s where all {request.principal.type = 'workload', request.principal.service_account = 'default', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to inspect buckets in compartment id %s where all {request.principal.type = 'workload', request.principal.service_account = 'default', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to read objects in compartment id %s where all {request.principal.type = 'workload', request.principal.service_account = 'default', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage load-balancers in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to use virtual-network-family in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage cabundles in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage cabundle-associations in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage leaf-certificates in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to read leaf-certificate-bundles in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage leaf-certificate-versions in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage certificate-associations in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to read certificate-authorities in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage certificate-authority-associations in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to read certificate-authority-bundles in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to read public-ips in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage floating-ips in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage waf-family in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to read cluster-family in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to use tag-namespaces in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'native-ingress-controller-system', request.principal.service_account = 'oci-native-ingress-controller', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    format("allow dynamic-group %s to manage repos in compartment id %s", oci_identity_dynamic_group.node_dynamic_group.name, var.compartment_id),
  ]
  provider = oci.home_region
}