# Example: Always Free deployment (A1.Flex compute + free-tier ADB)

# Run: examples/test.sh

# Deployment Configuration
label_prefix      = "CITEST"
optimizer_version = "Stable"
infrastructure    = "AlwaysFree"

# Compute - shape is forced to VM.Standard.A1.Flex when infrastructure="AlwaysFree";
# Always Free A1.Flex caps at 4 OCPU / 24 GB total per tenancy (6 GB/OCPU).
compute_cpu_ocpu = 4

# Load Balancer
lb_min_shape = 10
lb_max_shape = 10

# Network Access - Note that this will block all access
# You should specify a limited CIDR for your network
client_allowed_cidrs = "127.0.0.0/8"
server_allowed_cidrs = "127.0.0.0/8"
