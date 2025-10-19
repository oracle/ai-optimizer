# Oracle AI Optimizer - OpenTofu/Terraform Infrastructure as Code

This directory contains the OpenTofu/Terraform configuration for deploying the Oracle AI Optimizer on Oracle Cloud Infrastructure (OCI).

## Portability

This `opentofu/` directory is **designed to be portable** and can be copied to other projects or used standalone. It includes:

- ✅ Standalone `.gitignore` - Works when copied to another repo
- ✅ Example variable files - Safe placeholder credentials for testing
- ✅ Comprehensive documentation - Self-contained
- ✅ CI/CD testing configs - GitHub Actions workflow examples

### Using in Another Project

To use this infrastructure in another project:

1. **Copy the entire directory:**
   ```bash
   cp -r opentofu/ /path/to/your/project/
   cd /path/to/your/project/opentofu/
   ```

2. **The `.gitignore` is already configured:**
   - Blocks real credentials (`*.tfvars`, `*.pem`)
   - Allows example files (`examples/*.tfvars`)
   - Blocks state files and cache

3. **Start with an example:**
   ```bash
   cp examples/ci-vm-new-adb.tfvars terraform.tfvars
   # Edit terraform.tfvars with your real OCI credentials
   ```

4. **Deploy:**
   ```bash
   tofu init
   tofu plan
   tofu apply
   ```

## Directory Structure

```
opentofu/
├── README.md                    # This file
├── TESTING.md                   # CI/CD testing documentation
├── .gitignore                   # Portable .gitignore (works standalone)
├── examples/                    # Example variable files (safe to commit)
│   ├── README.md                # Documentation for examples
│   ├── ci-vm-new-adb.tfvars     # VM with new ADB
│   ├── ci-k8s-new-adb.tfvars    # Kubernetes with new ADB
│   └── ...                      # Other scenarios
├── *.tf                         # Main Terraform configuration
├── modules/                     # Terraform modules
│   ├── network/
│   ├── vm/
│   └── ...
└── cfgmgt/                      # Configuration management scripts
```

## .gitignore Strategy

This directory has its **own `.gitignore`** that works both:
- ✅ As part of this repo (with root `.gitignore`)
- ✅ When copied to another project (standalone)

**What's blocked:**
- `*.tfvars` - Real credentials (except `examples/*.tfvars`)
- `*.pem` - Private keys
- `.terraform*` - Provider cache
- `terraform.tfstate*` - State files
- `*.tfplan` - Plan output files

**What's allowed:**
- `examples/*.tfvars` - Safe placeholder credentials for CI/CD
- All `.tf` files - Infrastructure code
- Documentation files

## Example Variable Files

The `examples/` directory contains **safe-to-commit** variable files with placeholder credentials for:

1. **CI/CD Testing** - GitHub Actions uses these for validation
2. **Documentation** - Demonstrates different deployment scenarios
3. **Quick Start** - Copy as starting point for real deployments

**Important:** These files contain **fake OCIDs and credentials** and will not work for actual deployments.

See [`examples/README.md`](examples/README.md) for details on each scenario.

## Packaging IaC Stack

The IaC is packaged and attached to each release using GitHub Actions. Below is the manual procedure:

1. Zip the IaC with Archives
    ```bash
    zip -r ai-optimizer-iac.zip . \
      -x "terraform*" \
      -x ".terraform*" \
      -x "*/terraform*" \
      -x "*/.terraform*" \
      -x "cfgmgt/stage/*.*" \
      -x "*.tfplan*"
    ```

## version.tf

The `version.tf` file is automatically updated during the release cycle.
The contents should otherwise be `app_version = "0.0.0"` to indicate a non-release.

## Quick Start

### 1. Prerequisites

- OpenTofu/Terraform 1.5+
- OCI account with appropriate permissions
- OCI CLI configured (optional, for easier setup)

### 2. Configure Variables

```bash
# Option A: Use an example as template
cp examples/ci-vm-new-adb.tfvars terraform.tfvars

# Option B: Create from scratch
cat > terraform.tfvars << EOF
tenancy_ocid     = "ocid1.tenancy.oc1..aaa..."
compartment_ocid = "ocid1.compartment.oc1..aaa..."
user_ocid        = "ocid1.user.oc1..aaa..."
fingerprint      = "xx:xx:xx:..."
region           = "us-phoenix-1"
private_key_path = "./private_key.pem"

infrastructure   = "VM"
# ... other variables
EOF
```

### 3. Deploy

```bash
# Initialize
tofu init

# Preview changes
tofu plan

# Apply
tofu apply

# (Optional) Destroy when done
tofu destroy
```

## Testing

See [`TESTING.md`](TESTING.md) for details on the CI/CD testing strategy, including:

- How to run tests locally
- GitHub Actions workflow explanation
- Adding new test scenarios
- Performance optimizations

## Documentation

- **[TESTING.md](TESTING.md)** - CI/CD testing strategy and workflow details
- **[examples/README.md](examples/README.md)** - Example variable files documentation
- **[../.github/workflows/OPTIMIZATION.md](../.github/workflows/OPTIMIZATION.md)** - Workflow optimization details (if in original repo)

## Support

For issues or questions:

1. Check the documentation in this directory
2. Review the example files in `examples/`
3. See the main project README for general information