# OpenTofu Example Variable Files

This directory contains example `.tfvars` files for different deployment scenarios.

## Quick Start

```bash
# Load credentials from ~/.oci/config and run all tests
cd /path/to/your/project/opentofu/
examples/manual-test.sh
```

The test script automatically loads credentials from `~/.oci/config`, sets compartment to your tenancy root, and runs `tofu plan` on all testable examples.

## Example Scenarios

| File | Description | Infrastructure | Database |
|------|-------------|----------------|----------|
| `vm-new-adb.tfvars` | VM deployment with new Autonomous Database | VM | New ADB |
| `k8s-new-adb.tfvars` | Kubernetes deployment with new ADB | Kubernetes (OKE) | New ADB |
| `vm-arm-shape.tfvars` | VM with ARM (Ampere) compute shape | VM | New ADB (BYOL) |
| `vm-byo-adb.tfvars` | VM with bring-your-own ADB | VM | BYO ADB-S |
| `vm-byo-other-db.tfvars` | VM with BYO other database | VM | BYO OTHER |
| `k8s-byo-other-db.tfvars` | Kubernetes with BYO other database | Kubernetes (OKE) | BYO OTHER |

## Manual Setup (Without Helper Script)

If you prefer not to use the helper script:

1. Copy an example:
   ```bash
   cd /path/to/your/project/opentofu/
   cp examples/vm-new-adb.tfvars terraform.tfvars
   ```

2. Edit `terraform.tfvars` and uncomment/set the authentication variables:
   ```hcl
   tenancy_ocid     = "ocid1.tenancy.oc1..aaa..."
   compartment_ocid = "ocid1.compartment.oc1..aaa..."
   user_ocid        = "ocid1.user.oc1..aaa..."
   fingerprint      = "xx:xx:xx:..."
   private_key_path = "~/.oci/oci_api_key.pem"
   region           = "us-phoenix-1"
   ```

3. Run OpenTofu:
   ```bash
   tofu init
   tofu plan
   tofu apply
   ```

## OCI Config File Format

The helper script, `examples/manual-test.sh`, reads from `~/.oci/config` which should look like:

```ini
[DEFAULT]
user=ocid1.user.oc1..aaa...
tenancy=ocid1.tenancy.oc1..aaa...
region=us-phoenix-1
fingerprint=xx:xx:xx:...
key_file=~/.oci/oci_api_key.pem
```

If you don't have this file, run: `oci setup config`
