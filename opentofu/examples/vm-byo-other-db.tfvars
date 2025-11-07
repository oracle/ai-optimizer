# Example: VM deployment with BYO Other Database (non-ADB)

# Run: examples/test.sh

# Deployment Configuration
label_prefix      = "CITEST"
optimizer_version = "Stable"
infrastructure    = "VM"

# BYO Other Database
byo_db_type     = "OTHER"
byo_db_password = "FakePassword123!NotReal"
byo_odb_host    = "fake-db-host.example.com"
byo_odb_port    = 1521
byo_odb_service = "FAKEPDB.example.com"

# Compute
compute_cpu_shape = "VM.Standard.E5.Flex"
compute_cpu_ocpu  = 2

# Load Balancer
lb_min_shape = 10
lb_max_shape = 10

# Network Access
client_allowed_cidrs = "10.0.0.0/8"
server_allowed_cidrs = "10.0.0.0/8"
