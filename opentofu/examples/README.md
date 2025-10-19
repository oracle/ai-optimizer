# OpenTofu Example Variable Files

This directory contains example `.tfvars` files for different deployment scenarios. These files are primarily used for:

1. **CI/CD Testing**: GitHub Actions uses these to validate OpenTofu plans without requiring real OCI credentials
2. **Documentation**: Demonstrating different deployment configurations
3. **Local Testing**: Quick starting points for different scenarios

## Files

### CI/CD Test Scenarios (with placeholder credentials)

| File | Description | Infrastructure | Database |
|------|-------------|----------------|----------|
| `ci-vm-new-adb.tfvars` | VM deployment with new Autonomous Database | VM | New ADB |
| `ci-k8s-new-adb.tfvars` | Kubernetes deployment with new ADB | Kubernetes (OKE) | New ADB |
| `ci-vm-byo-adb.tfvars` | VM with bring-your-own ADB | VM | BYO ADB-S |
| `ci-k8s-byo-other-db.tfvars` | Kubernetes with BYO other database | Kubernetes (OKE) | BYO OTHER |
| `ci-vm-arm-shape.tfvars` | VM with ARM (Ampere) compute shape | VM | New ADB (BYOL) |

## Using These Files

### For GitHub Actions CI/CD

The GitHub Actions workflow automatically uses these files to test different deployment scenarios:

```bash
tofu init -backend=false
tofu plan -var-file=examples/ci-vm-new-adb.tfvars
```

These plans will validate the OpenTofu configuration logic without requiring real OCI authentication.

### For Local Development

**Important**: These files contain placeholder credentials and will not work for actual deployments.

To use these as templates for real deployments:

1. Copy an example file:
   ```bash
   cp examples/ci-vm-new-adb.tfvars terraform.tfvars
   ```

2. Edit `terraform.tfvars` with your real OCI credentials:
   ```hcl
   tenancy_ocid     = "ocid1.tenancy.oc1..aaaaaaaayour-real-tenancy-ocid"
   compartment_ocid = "ocid1.compartment.oc1..aaaaaaaayour-real-compartment-ocid"
   user_ocid        = "ocid1.user.oc1..aaaaaaaayour-real-user-ocid"
   fingerprint      = "your:real:fingerprint:here"
   region           = "us-phoenix-1"
   private_key_path = "/path/to/your/private_key.pem"
   ```

3. Run OpenTofu:
   ```bash
   tofu init
   tofu plan
   tofu apply
   ```

## Contributing

When adding new deployment scenarios:

1. Create a new `ci-*.tfvars` file with a descriptive name
2. Use placeholder credentials (fake OCIDs, fingerprints)
3. Add comments explaining the scenario
4. Update this README with the new scenario
5. Update `.github/workflows/opentofu.yml` matrix to include the new file
