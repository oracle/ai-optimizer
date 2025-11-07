# Example: Kubernetes deployment with new Autonomous Database

# Run: examples/test.sh

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
