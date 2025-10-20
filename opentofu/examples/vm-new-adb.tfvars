# Example: VM deployment with new Autonomous Database

# Run: examples/test.sh

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
