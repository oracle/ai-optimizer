# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

locals {
  optimizer_oci_username = var.deploy_optimizer ? data.oci_identity_user.optimizer_admin[0].name : ""
  optimizer_identity_domain_name = var.deploy_optimizer && strcontains(local.optimizer_oci_username, "/") ? (
    split("/", local.optimizer_oci_username)[0]
  ) : null
  optimizer_identity_domain_username = var.deploy_optimizer ? element(
    reverse(split("/", local.optimizer_oci_username)),
    0,
  ) : ""
  optimizer_identity_domain = var.deploy_optimizer ? one(data.oci_identity_domains.optimizer[0].domains) : null
  optimizer_admin_user      = var.deploy_optimizer ? one(data.oci_identity_domains_users.optimizer_admin[0].users) : null
  oidc_issuer               = var.deploy_optimizer ? "https://identity.oraclecloud.com/" : ""
  oidc_discovery_url        = var.deploy_optimizer ? "${trimsuffix(local.optimizer_identity_domain.url, "/")}/.well-known/openid-configuration" : ""
  oidc_audience             = var.deploy_optimizer ? "${local.optimizer_server_base_url}/" : ""
  oidc_scope                = var.deploy_optimizer ? "${local.oidc_audience}invoke" : ""
  oidc_required_scopes      = var.deploy_optimizer ? toset([local.oidc_scope]) : toset([])
  oidc_redirect_uri         = var.deploy_optimizer ? "${local.optimizer_client_url}/oauth2callback" : ""
  oidc_admin_subject        = var.deploy_optimizer ? local.optimizer_admin_user.user_name : ""
  oidc_public_server_url    = var.deploy_optimizer ? local.optimizer_server_base_url : ""
  oidc_client_id            = var.deploy_optimizer ? oci_identity_domains_app.optimizer[0].name : ""
  oidc_client_secret        = var.deploy_optimizer ? sensitive(oci_identity_domains_app.optimizer[0].client_secret) : sensitive("")
}

data "oci_identity_domains_users" "optimizer_admin" {
  count         = var.deploy_optimizer ? 1 : 0
  idcs_endpoint = local.optimizer_identity_domain.url
  user_filter = format(
    "userName eq \"%s\"",
    replace(local.optimizer_identity_domain_username, "\"", "\\\""),
  )
  provider = oci.home_region
}
resource "oci_identity_domains_app" "optimizer" {
  count         = var.deploy_optimizer ? 1 : 0
  idcs_endpoint = local.optimizer_identity_domain.url
  schemas       = ["urn:ietf:params:scim:schemas:oracle:idcs:App"]
  display_name  = format("%s AI Optimizer", local.label_prefix)
  description   = "OIDC client and resource server for AI Optimizer."

  based_on_template {
    value = "CustomWebAppTemplateId"
  }

  active               = true
  allow_access_control = true
  allowed_grants       = ["authorization_code"]
  audience             = local.oidc_audience
  client_type          = "trusted"
  force_delete         = true
  is_oauth_client      = true
  is_oauth_resource    = true
  redirect_uris        = [local.oidc_redirect_uri]
  trust_scope          = "Explicit"

  allowed_scopes {
    fqs = local.oidc_scope
  }

  scopes {
    value            = "invoke"
    display_name     = "Invoke AI Optimizer"
    description      = "Use the AI Optimizer API."
    requires_consent = false
  }

  provider = oci-patched.home_region
  lifecycle {
    // cannot change from PRIVATE_ENDPOINT_ACCESS to SECURE_ACCESS
    ignore_changes = [schemas]
  }
}

resource "oci_identity_domains_grant" "optimizer_admin" {
  count           = var.deploy_optimizer ? 1 : 0
  idcs_endpoint   = local.optimizer_identity_domain.url
  grant_mechanism = "ADMINISTRATOR_TO_USER"
  schemas         = ["urn:ietf:params:scim:schemas:oracle:idcs:Grant"]

  grantee {
    type  = "User"
    value = local.optimizer_admin_user.id
  }

  app {
    value = oci_identity_domains_app.optimizer[0].id
  }

  provider = oci.home_region
}
