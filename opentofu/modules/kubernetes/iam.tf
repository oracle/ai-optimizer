# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

resource "oci_identity_dynamic_group" "workers_dynamic_group" {
  compartment_id = var.tenancy_id
  name           = format("%s-worker-dyngrp", var.label_prefix)
  description    = format("%s Workers Dynamic Group", var.label_prefix)
  matching_rule = format(
    "ALL {instance.compartment.id = '%s', tag.Oracle-Tags.CreatedBy.value = '%s'}",
  var.compartment_id, oci_containerengine_node_pool.cpu_node_pool_details.id)
  provider = oci.home_region
}

resource "oci_identity_policy" "workers_policies" {
  compartment_id = var.tenancy_id
  name           = format("%s-workers-policy", var.label_prefix)
  description    = format("%s - K8s Workers", var.label_prefix)
  statements = [
    # Workload Principles specific to oracle-database-operator-system Namespace
    format("allow any-user to manage autonomous-database-family in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = 'oracle-database-operator-system', request.principal.service_account = 'default', request.principal.cluster_id = '%s'}", var.compartment_id, oci_containerengine_cluster.default_cluster.id),
    # Workload Principles specific to native-ingress-controller-system Namespace
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
    # Workload Principles specific to Custom Namespace
    format("allow any-user to read objectstorage-namespaces in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = '%s', request.principal.cluster_id = '%s'}", var.compartment_id, var.label_prefix, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to inspect buckets in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = '%s', request.principal.cluster_id = '%s'}", var.compartment_id, var.label_prefix, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to read objects in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = '%s', request.principal.cluster_id = '%s'}", var.compartment_id, var.label_prefix, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to manage repos in compartment id %s where all {request.principal.type = 'workload', request.principal.namespace = '%s', request.principal.cluster_id = '%s'}", var.compartment_id, var.label_prefix, oci_containerengine_cluster.default_cluster.id),
    format("allow any-user to use generative-ai-family in tenancy where all {request.principal.type = 'workload', request.principal.namespace = '%s', request.principal.cluster_id = '%s'}", var.label_prefix, oci_containerengine_cluster.default_cluster.id),
    # Instance Principals (required to pull images)
    format("allow dynamic-group %s to manage repos in compartment id %s", oci_identity_dynamic_group.workers_dynamic_group.name, var.compartment_id),
  ]
  provider = oci.home_region
}