# Example: Kubernetes with BYO Other Database (non-ADB)

# Run: examples/test.sh

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
