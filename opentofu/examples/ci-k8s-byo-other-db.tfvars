# CI/CD Test Scenario: Kubernetes with BYO Other Database (non-ADB)
# This file contains placeholder values for GitHub Actions validation

# Required OCI Authentication (placeholders for validation only)
tenancy_ocid     = "ocid1.tenancy.oc1..aaaaaaaafaketenancyocidforgithubactionstesting"
compartment_ocid = "ocid1.compartment.oc1..aaaaaaaafakecompartmentocidforgithubactions"
user_ocid        = "ocid1.user.oc1..aaaaaaaafakeuserocidforgithubactionstesting"
fingerprint      = "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"
private_key      = "-----BEGIN RSA PRIVATE KEY-----\nFAKEKEYFORCITESTINGONLY\n-----END RSA PRIVATE KEY-----"
region           = "eu-frankfurt-1"

# Deployment Configuration
label_prefix      = "CITEST"
optimizer_version = "Experimental"
infrastructure    = "Kubernetes"

# BYO Other Database
byo_db_type     = "OTHER"
byo_db_password = "FakePassword123!NotReal"
byo_odb_host    = "fake-db-host.example.com"
byo_odb_port    = 1521
byo_odb_service = "FAKEPDB.example.com"

# Compute
compute_cpu_shape = "VM.Standard.A1.Flex"
compute_cpu_ocpu  = 4

# Load Balancer
lb_min_shape = 10
lb_max_shape = 50
