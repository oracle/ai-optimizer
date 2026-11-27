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

data "oci_identity_domains_setting" "optimizer" {
  count          = var.deploy_optimizer ? 1 : 0
  idcs_endpoint  = local.optimizer_identity_domain.url
  setting_id     = "Settings"
  attribute_sets = ["all"]
  provider       = oci.home_region
}

resource "oci_identity_domains_setting" "optimizer" {
  count         = var.deploy_optimizer ? 1 : 0
  csr_access    = data.oci_identity_domains_setting.optimizer[0].csr_access
  idcs_endpoint = local.optimizer_identity_domain.url
  schemas       = ["urn:ietf:params:scim:schemas:oracle:idcs:Settings"]
  setting_id    = "Settings"

  # Settings is replaced as a whole, so carry forward its current writable values.
  account_always_trust_scope                                 = data.oci_identity_domains_setting.optimizer[0].account_always_trust_scope
  allowed_domains                                            = data.oci_identity_domains_setting.optimizer[0].allowed_domains
  allowed_forgot_password_flow_return_urls                   = data.oci_identity_domains_setting.optimizer[0].allowed_forgot_password_flow_return_urls
  allowed_notification_redirect_urls                         = data.oci_identity_domains_setting.optimizer[0].allowed_notification_redirect_urls
  attribute_sets                                             = ["all"]
  audit_event_retention_period                               = data.oci_identity_domains_setting.optimizer[0].audit_event_retention_period
  cloud_migration_custom_url                                 = data.oci_identity_domains_setting.optimizer[0].cloud_migration_custom_url
  cloud_migration_url_enabled                                = data.oci_identity_domains_setting.optimizer[0].cloud_migration_url_enabled
  contact_emails                                             = data.oci_identity_domains_setting.optimizer[0].contact_emails
  custom_branding                                            = data.oci_identity_domains_setting.optimizer[0].custom_branding
  custom_css_location                                        = data.oci_identity_domains_setting.optimizer[0].custom_css_location
  custom_html_location                                       = data.oci_identity_domains_setting.optimizer[0].custom_html_location
  custom_translation                                         = data.oci_identity_domains_setting.optimizer[0].custom_translation
  default_trust_scope                                        = data.oci_identity_domains_setting.optimizer[0].default_trust_scope
  diagnostic_level                                           = data.oci_identity_domains_setting.optimizer[0].diagnostic_level
  diagnostic_record_for_search_identifies_returned_resources = data.oci_identity_domains_setting.optimizer[0].diagnostic_record_for_search_identifies_returned_resources
  enable_terms_of_use                                        = data.oci_identity_domains_setting.optimizer[0].enable_terms_of_use
  external_id                                                = data.oci_identity_domains_setting.optimizer[0].external_id
  iam_upst_session_expiry                                    = data.oci_identity_domains_setting.optimizer[0].iam_upst_session_expiry
  is_hosted_page                                             = data.oci_identity_domains_setting.optimizer[0].is_hosted_page
  issuer                                                     = data.oci_identity_domains_setting.optimizer[0].issuer
  locale                                                     = data.oci_identity_domains_setting.optimizer[0].locale
  max_no_of_app_cmva_to_return                               = data.oci_identity_domains_setting.optimizer[0].max_no_of_app_cmva_to_return
  max_no_of_app_role_members_to_return                       = data.oci_identity_domains_setting.optimizer[0].max_no_of_app_role_members_to_return
  preferred_language                                         = data.oci_identity_domains_setting.optimizer[0].preferred_language
  prev_issuer                                                = data.oci_identity_domains_setting.optimizer[0].prev_issuer
  privacy_policy_url                                         = data.oci_identity_domains_setting.optimizer[0].privacy_policy_url
  re_auth_factor                                             = data.oci_identity_domains_setting.optimizer[0].re_auth_factor
  re_auth_when_changing_my_authentication_factors            = data.oci_identity_domains_setting.optimizer[0].re_auth_when_changing_my_authentication_factors
  service_admin_cannot_list_other_users                      = data.oci_identity_domains_setting.optimizer[0].service_admin_cannot_list_other_users
  signing_cert_public_access                                 = true
  sub_mapping_attr                                           = data.oci_identity_domains_setting.optimizer[0].sub_mapping_attr
  terms_of_use_url                                           = data.oci_identity_domains_setting.optimizer[0].terms_of_use_url
  timezone                                                   = data.oci_identity_domains_setting.optimizer[0].timezone

  dynamic "certificate_validation" {
    for_each = data.oci_identity_domains_setting.optimizer[0].certificate_validation
    content {
      crl_check_on_ocsp_failure_enabled     = certificate_validation.value.crl_check_on_ocsp_failure_enabled
      crl_enabled                           = certificate_validation.value.crl_enabled
      crl_location                          = certificate_validation.value.crl_location
      crl_refresh_interval                  = certificate_validation.value.crl_refresh_interval
      ocsp_enabled                          = certificate_validation.value.ocsp_enabled
      ocsp_responder_url                    = certificate_validation.value.ocsp_responder_url
      ocsp_settings_responder_url_preferred = certificate_validation.value.ocsp_settings_responder_url_preferred
      ocsp_signing_certificate_alias        = certificate_validation.value.ocsp_signing_certificate_alias
      ocsp_timeout_duration                 = certificate_validation.value.ocsp_timeout_duration
      ocsp_unknown_response_status_allowed  = certificate_validation.value.ocsp_unknown_response_status_allowed
    }
  }

  dynamic "cloud_gate_cors_settings" {
    for_each = data.oci_identity_domains_setting.optimizer[0].cloud_gate_cors_settings
    content {
      cloud_gate_cors_allow_null_origin = cloud_gate_cors_settings.value.cloud_gate_cors_allow_null_origin
      cloud_gate_cors_allowed_origins   = cloud_gate_cors_settings.value.cloud_gate_cors_allowed_origins
      cloud_gate_cors_enabled           = cloud_gate_cors_settings.value.cloud_gate_cors_enabled
      cloud_gate_cors_exposed_headers   = cloud_gate_cors_settings.value.cloud_gate_cors_exposed_headers
      cloud_gate_cors_max_age           = cloud_gate_cors_settings.value.cloud_gate_cors_max_age
    }
  }

  dynamic "company_names" {
    for_each = data.oci_identity_domains_setting.optimizer[0].company_names
    content {
      locale = company_names.value.locale
      value  = company_names.value.value
    }
  }

  dynamic "images" {
    for_each = data.oci_identity_domains_setting.optimizer[0].images
    content {
      display = images.value.display
      type    = images.value.type
      value   = images.value.value
    }
  }

  dynamic "login_texts" {
    for_each = data.oci_identity_domains_setting.optimizer[0].login_texts
    content {
      locale = login_texts.value.locale
      value  = login_texts.value.value
    }
  }

  dynamic "purge_configs" {
    for_each = data.oci_identity_domains_setting.optimizer[0].purge_configs
    content {
      resource_name    = purge_configs.value.resource_name
      retention_period = purge_configs.value.retention_period
    }
  }

  dynamic "tags" {
    for_each = data.oci_identity_domains_setting.optimizer[0].tags
    content {
      key   = tags.value.key
      value = tags.value.value
    }
  }

  dynamic "tenant_custom_claims" {
    for_each = data.oci_identity_domains_setting.optimizer[0].tenant_custom_claims
    content {
      all_scopes = tenant_custom_claims.value.all_scopes
      expression = tenant_custom_claims.value.expression
      mode       = tenant_custom_claims.value.mode
      name       = tenant_custom_claims.value.name
      scopes     = tenant_custom_claims.value.scopes
      token_type = tenant_custom_claims.value.token_type
      value      = tenant_custom_claims.value.value
    }
  }

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
