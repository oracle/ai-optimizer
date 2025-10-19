# CI/CD Test Scenario: VM deployment with new Autonomous Database
# This file contains placeholder values for GitHub Actions validation

# Required OCI Authentication (placeholders for validation only)
tenancy_ocid     = "ocid1.tenancy.oc1..aaaaaaaafaketenancyocidforgithubactionstesting"
compartment_ocid = "ocid1.compartment.oc1..aaaaaaaafakecompartmentocidforgithubactions"
user_ocid        = "ocid1.user.oc1..aaaaaaaafakeuserocidforgithubactionstesting"
fingerprint      = "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"
region           = "us-phoenix-1"
# private_key_path not set - plan will fail auth but validate logic

# Deployment Configuration
label_prefix      = "CITEST"
optimizer_version = "Stable"
infrastructure    = "VM"

# New Autonomous Database (not BYO)
# byo_db_type not set - will create new ADB
adb_ecpu_core_count             = 2
adb_data_storage_size_in_gb     = 20
adb_is_cpu_auto_scaling_enabled = true
adb_license_model               = "LICENSE_INCLUDED"
adb_networking                  = "SECURE_ACCESS"
adb_whitelist_cidrs             = "0.0.0.0/0"

# Compute
compute_cpu_shape = "VM.Standard.E5.Flex"
compute_cpu_ocpu  = 2

# Load Balancer
lb_min_shape = 10
lb_max_shape = 10

# Network Access
client_allowed_cidrs = "0.0.0.0/0"
server_allowed_cidrs = "0.0.0.0/0"
