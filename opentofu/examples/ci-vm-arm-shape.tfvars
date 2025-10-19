# CI/CD Test Scenario: VM with ARM (Ampere) compute shape
# This file contains placeholder values for GitHub Actions validation

# Required OCI Authentication (placeholders for validation only)
tenancy_ocid     = "ocid1.tenancy.oc1..aaaaaaaafaketenancyocidforgithubactionstesting"
compartment_ocid = "ocid1.compartment.oc1..aaaaaaaafakecompartmentocidforgithubactions"
user_ocid        = "ocid1.user.oc1..aaaaaaaafakeuserocidforgithubactionstesting"
fingerprint      = "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"
region           = "ap-tokyo-1"

# Deployment Configuration
label_prefix      = "CITEST"
optimizer_version = "Stable"
infrastructure    = "VM"

# New ADB with BYOL
adb_ecpu_core_count = 4
adb_license_model   = "BRING_YOUR_OWN_LICENSE"
adb_edition         = "ENTERPRISE_EDITION"
adb_networking      = "SECURE_ACCESS"
adb_whitelist_cidrs = "192.168.0.0/16"

# ARM Compute Shape
compute_cpu_shape = "VM.Standard.A1.Flex"
compute_cpu_ocpu  = 4

# Load Balancer
lb_min_shape = 10
lb_max_shape = 10
