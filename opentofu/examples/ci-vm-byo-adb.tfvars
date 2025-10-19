# CI/CD Test Scenario: VM deployment with BYO Autonomous Database
# This file contains placeholder values for GitHub Actions validation

# Required OCI Authentication (placeholders for validation only)
tenancy_ocid     = "ocid1.tenancy.oc1..aaaaaaaafaketenancyocidforgithubactionstesting"
compartment_ocid = "ocid1.compartment.oc1..aaaaaaaafakecompartmentocidforgithubactions"
user_ocid        = "ocid1.user.oc1..aaaaaaaafakeuserocidforgithubactionstesting"
fingerprint      = "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"
region           = "us-phoenix-1"

# Deployment Configuration
label_prefix      = "CITEST"
optimizer_version = "Stable"
infrastructure    = "VM"

# BYO Autonomous Database
byo_db_type     = "ADB-S"
byo_adb_ocid    = "ocid1.autonomousdatabase.oc1.phx.aaaaaaaafakeadbocidforgithubactions"
byo_db_password = "FakePassword123!NotReal"

# Compute
compute_cpu_shape = "VM.Standard.E5.Flex"
compute_cpu_ocpu  = 2

# Load Balancer
lb_min_shape = 10
lb_max_shape = 10

# Network Access
client_allowed_cidrs = "10.0.0.0/8"
server_allowed_cidrs = "10.0.0.0/8"
