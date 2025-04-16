# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

resource "random_string" "api_key" {
  length  = 32
  special = false
  upper   = false
}

// oci_artifacts_container_repository
resource "oci_artifacts_container_repository" "server_repository" {
  compartment_id = var.compartment_id
  display_name   = lower(format("%s/server", var.label_prefix))
  is_immutable   = false
  is_public      = false
}

resource "oci_artifacts_container_repository" "explorer_repository" {
  compartment_id = var.compartment_id
  display_name   = lower(format("%s/client", var.label_prefix))
  is_immutable   = false
  is_public      = false
}

resource "local_sensitive_file" "kubeconfig" {
  content         = data.oci_containerengine_cluster_kube_config.default_cluster_kube_config.content
  filename        = "${path.root}/generated/kubeconfig"
  file_permission = 0600
}

resource "local_sensitive_file" "helm_values" {
  content         = local.helm_values
  filename        = "${path.root}/generated/${var.label_prefix}-values.yaml"
  file_permission = 0600
}

resource "local_sensitive_file" "k8s_manifest" {
  content         = local.k8s_manifest
  filename        = "${path.root}/generated/${var.label_prefix}-manifest.yaml"
  file_permission = 0600
}

// Cluster
resource "oci_containerengine_cluster" "default_cluster" {
  compartment_id     = var.compartment_id
  kubernetes_version = format("v%s", var.k8s_version)
  name               = local.k8s_cluster_name
  vcn_id             = var.vcn_id
  type               = "ENHANCED_CLUSTER"

  cluster_pod_network_options {
    cni_type = "FLANNEL_OVERLAY"
  }

  endpoint_config {
    // Avoid K8s destruction by limiting access via is_public_ip_enabled and nsg_ids.  Keep on public subnet.
    is_public_ip_enabled = var.k8s_api_is_public
    nsg_ids              = [oci_core_network_security_group.k8s_api_endpoint.id]
    subnet_id            = var.public_subnet_id
  }

  image_policy_config {
    is_policy_enabled = false
  }
  options {
    add_ons {
      is_kubernetes_dashboard_enabled = false
      is_tiller_enabled               = false
    }

    admission_controller_options {
      is_pod_security_policy_enabled = "false"
    }
    persistent_volume_config {
      freeform_tags = {
        "clusterName" = local.k8s_cluster_name
      }
    }
    service_lb_config {
      freeform_tags = {
        "clusterName" = local.k8s_cluster_name
      }
    }
    service_lb_subnet_ids = [var.public_subnet_id]
  }
  freeform_tags = {
    "clusterName" = local.k8s_cluster_name
  }
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags]
  }
}

resource "oci_containerengine_addon" "oraoper_addon" {
  addon_name                       = "OracleDatabaseOperator"
  cluster_id                       = oci_containerengine_cluster.default_cluster.id
  remove_addon_resources_on_delete = true
}

resource "oci_containerengine_addon" "certmgr_addon" {
  addon_name                       = "CertManager"
  cluster_id                       = oci_containerengine_cluster.default_cluster.id
  remove_addon_resources_on_delete = true
}

resource "oci_containerengine_addon" "ingress_addon" {
  addon_name                       = "NativeIngressController"
  cluster_id                       = oci_containerengine_cluster.default_cluster.id
  remove_addon_resources_on_delete = true
  configurations {
    key   = "compartmentId"
    value = var.compartment_id
  }
  configurations {
    key   = "loadBalancerSubnetId"
    value = var.public_subnet_id
  }
  configurations {
    key   = "authType"
    value = "workloadIdentity"
  }
}

resource "oci_containerengine_node_pool" "default_node_pool_details" {
  cluster_id         = oci_containerengine_cluster.default_cluster.id
  compartment_id     = var.compartment_id
  kubernetes_version = format("v%s", var.k8s_version)
  name               = format("%s-np-default", var.label_prefix)
  initial_node_labels {
    key   = "name"
    value = local.k8s_cluster_name
  }
  node_config_details {
    node_pool_pod_network_option_details {
      cni_type = "FLANNEL_OVERLAY"
    }
    dynamic "placement_configs" {
      for_each = var.availability_domains
      iterator = ad
      content {
        availability_domain = ad.value
        subnet_id           = var.private_subnet_id
      }
    }
    size    = var.k8s_cpu_node_pool_size
    nsg_ids = [oci_core_network_security_group.k8s_workers.id]
    // Used for Instance Principles
    defined_tags = { (local.identity_tag_key) = local.identity_tag_val }
  }
  node_eviction_node_pool_settings {
    eviction_grace_duration              = "PT5M"
    is_force_delete_after_grace_duration = true
  }
  node_pool_cycling_details {
    is_node_cycling_enabled = true
    maximum_surge           = "25%"
    maximum_unavailable     = "25%"
  }
  node_shape = var.compute_cpu_shape
  node_shape_config {
    memory_in_gbs = var.compute_cpu_ocpu * 16
    ocpus         = var.compute_cpu_ocpu
  }
  node_source_details {
    image_id    = local.oke_worker_cpu_image
    source_type = "IMAGE"
  }
  node_metadata = {
    user_data = data.cloudinit_config.workers.rendered
  }
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags, node_config_details[0].size]
  }
}

resource "oci_containerengine_node_pool" "gpu_node_pool_details" {
  cluster_id         = oci_containerengine_cluster.default_cluster.id
  compartment_id     = var.compartment_id
  kubernetes_version = format("v%s", var.k8s_version)
  name               = format("%s-np-gpu", var.label_prefix)
  initial_node_labels {
    key   = "name"
    value = local.k8s_cluster_name
  }
  node_config_details {
    node_pool_pod_network_option_details {
      cni_type = "FLANNEL_OVERLAY"
    }
    dynamic "placement_configs" {
      for_each = local.gpu_availability_domains
      iterator = ad
      content {
        availability_domain = ad.value
        subnet_id           = var.private_subnet_id
      }
    }
    size    = var.k8s_gpu_node_pool_size
    nsg_ids = [oci_core_network_security_group.k8s_workers.id]
  }
  node_eviction_node_pool_settings {
    eviction_grace_duration              = "PT5M"
    is_force_delete_after_grace_duration = true
  }
  node_pool_cycling_details {
    is_node_cycling_enabled = true
    maximum_surge           = "25%"
    maximum_unavailable     = "25%"
  }
  node_shape = var.compute_gpu_shape
  node_source_details {
    image_id                = local.oke_worker_gpu_image
    source_type             = "IMAGE"
    boot_volume_size_in_gbs = 100
  }
  node_metadata = {
    user_data = data.cloudinit_config.workers.rendered
  }
  lifecycle {
    ignore_changes = [defined_tags, freeform_tags, node_config_details[0].size]
  }
}