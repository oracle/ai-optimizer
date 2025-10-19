# CI/CD Test Scenario: Kubernetes deployment with new Autonomous Database
# This file contains placeholder values for GitHub Actions validation

# Required OCI Authentication (placeholders for validation only)
tenancy_ocid     = "ocid1.tenancy.oc1..aaaaaaaafaketenancyocidforgithubactionstesting"
compartment_ocid = "ocid1.compartment.oc1..aaaaaaaafakecompartmentocidforgithubactions"
user_ocid        = "ocid1.user.oc1..aaaaaaaafakeuserocidforgithubactionstesting"
fingerprint      = "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"
private_key      = "-----BEGIN RSA PRIVATE KEY-----\nFAKEKEYFORCITESTINGONLY\n-----END RSA PRIVATE KEY-----"
region           = "us-ashburn-1"

# Deployment Configuration
label_prefix      = "CITEST"
optimizer_version = "Stable"
infrastructure    = "Kubernetes"

# New Autonomous Database
adb_ecpu_core_count             = 2
adb_data_storage_size_in_gb     = 20
adb_is_cpu_auto_scaling_enabled = true
adb_license_model               = "LICENSE_INCLUDED"
adb_networking                  = "PRIVATE_ENDPOINT_ACCESS"
adb_whitelist_cidrs             = ""

# Compute
compute_cpu_shape = "VM.Standard.E4.Flex"
compute_cpu_ocpu  = 2

# Load Balancer
lb_min_shape = 10
lb_max_shape = 100
