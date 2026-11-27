# Project-local OCI provider

OpenTofu uses `local.project/ai-optimizer/oci` for the resources that require fixes pending in the upstream OCI provider.

Version `9.15.0-patched.1` was built from OCI provider commit `2e05bde70b` with fixes from:

- `aa380753fb` from `2026-fixes`
- `b7403d8539` and `a286bca197` from `2071-fixes`
- `97a2cbc137` from `2671-fixes`
- the current `2671-fixes` working-tree diagnostic for subject and SAN conflicts
- `79510729ca4ff522d36fe0e461246807dd468be6` from PR `#2469`, using the App Status Changer API

Packages:

- `darwin_arm64`: `77352f95d15fc50131cb02b3efb47b0ebe738c18d4c2dca51c00fbeff1b79af1`
- `linux_amd64`: `85137ad3eb4b727ff95d26d22c05bb1a9d196d08769fe4bd25ff3cf0f09856f9`

The main root assigns the patched provider to `oci_objectstorage_bucket.bucket`, `oci_identity_domains_app.optimizer`, and `oci_certificates_management_certificate.lb_cert`.
