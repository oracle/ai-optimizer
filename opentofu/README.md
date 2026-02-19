# Oracle AI Optimizer - OpenTofu/Terraform Infrastructure as Code

This directory contains the OpenTofu/Terraform configuration for deploying the Oracle AI Optimizer on Oracle Cloud Infrastructure (OCI).

## Directory Structure

```
opentofu/
├── README.md                    # This file
├── TESTING.md                   # CI/CD testing documentation
├── .gitignore                   # Portable .gitignore (works standalone)
├── examples/                    # Example variable files; **see note below**
│   ├── README.md                # Documentation for examples
│   ├── vm-new-adb.tfvars        # VM with new ADB
│   ├── k8s-new-adb.tfvars       # Kubernetes with new ADB
│   └── ...                      # Other scenarios
├── *.tf                         # Main Terraform configuration
├── versions.tf                  # Track Versions; **see note below**
├── modules/                     # Terraform modules
│   ├── network/
│   ├── kubernetes/
│   └── ...
└── cfgmgt/                      # Configuration management scripts
```

### version.tf

The `version.tf` file is automatically updated during the release cycle.
The contents should otherwise be `app_version = "0.0.0"` to indicate a non-release.

### Example Variable Files

The `examples/` directory contains variable files with placeholder credentials for:

1. **Documentation** - Demonstrates different deployment scenarios
2. **Manual Testing** - Templates for testing with real OCI credentials
3. **Quick Start** - Copy as starting point for real deployments

**Important:** These files contain **placeholder OCIDs and credentials** and will not work for actual deployments. Replace with your real OCI credentials before running `tofu plan`.

See [`examples/README.md`](examples/README.md) for details on each scenario.

## Packaging IaC Stack

The IaC is packaged and attached to each release using GitHub Actions. Below is the manual procedure:

1. Zip the IaC with Archives
    ```bash
    zip -r ai-optimizer-iac.zip . \
      -x "terraform*" ".terraform*" "*/terraform*" "*/.terraform*" \
      -x "cfgmgt/stage/*.*" "*.tfplan*" "examples/*" "*.md" ".gitignore"
    ```

## Quick Start

### 1. Prerequisites

- OpenTofu/Terraform 1.5+
- OCI account with appropriate permissions
- OCI CLI configured (optional, for easier setup)

### 2. Configure Variables

```bash
# Option A: Use an example as template
cp examples/vm-new-adb.tfvars terraform.tfvars

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

## Portability

This `opentofu/` directory is **designed to be portable** and can be copied to other projects or used standalone. It includes:

- ✅ Standalone `.gitignore` - Works when copied to another repo
- ✅ Self-contained modules - Remove modules if not applicable
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

2. **Remove modules that are not required (e.g. VM infrastructure):**
   ```bash
   cd /path/to/your/project/opentofu/
   rm module_vm.tf
   rm -rf modules/vm
   ```

3. **Start with an example:**
   ```bash
   cp examples/vm-new-adb.tfvars terraform.tfvars
   # Edit terraform.tfvars with your real OCI credentials
   ```

4. **Deploy:**
   ```bash
   tofu init
   tofu plan
   tofu apply
   ```

## Testing

See [`TESTING.md`](TESTING.md) for manual testing requirements. **CI validates syntax only** - infrastructure logic must be tested with real OCI credentials before merging changes.

## Documentation

- **[TESTING.md](TESTING.md)** - CI/CD testing strategy and workflow details
- **[examples/README.md](examples/README.md)** - Example variable files documentation

## Support

For issues or questions:

1. Check the documentation in this directory
2. Review the example files in `examples/`