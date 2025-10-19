# OpenTofu Testing Strategy

This document describes the automated testing strategy for the Oracle AI Optimizer OpenTofu/Terraform infrastructure code.

## Overview

The GitHub Actions workflow `.github/workflows/opentofu.yml` provides comprehensive validation without requiring real OCI credentials by using placeholder values and testing multiple deployment scenarios.

## Testing Jobs

### 1. Basic Validation (`verify-iac-basic`)

**Purpose**: Validate syntax, formatting, and schema compliance

**Steps**:
- ✅ `terraform init -backend=false` - Initialize without remote state
- ✅ `terraform validate` - Validate HCL syntax and configuration
- ✅ `terraform fmt -recursive -check` - Ensure consistent formatting
- ✅ Schema validation against Oracle Resource Manager specifications

**When it runs**: On every PR and manual workflow dispatch

### 2. Plan Validation (`verify-iac-plans`)

**Purpose**: Test deployment logic across different scenarios using matrix strategy

**Scenarios Tested**:

| Scenario | Infrastructure | Database | Compute | Purpose |
|----------|---------------|----------|---------|---------|
| **VM + New ADB** | Virtual Machine | New Autonomous DB | E5.Flex (AMD) | Basic VM deployment |
| **K8s + New ADB** | Kubernetes (OKE) | New Autonomous DB | E4.Flex (AMD) | Production K8s deployment |
| **VM + BYO ADB** | Virtual Machine | Existing ADB | E5.Flex (AMD) | BYO database scenario |
| **K8s + BYO Other DB** | Kubernetes (OKE) | Other Oracle DB | A1.Flex (ARM) | Non-ADB integration |
| **VM + ARM Shape** | Virtual Machine | New ADB (BYOL) | A1.Flex (ARM) | ARM compute testing |

**How it works**:
1. Each scenario runs in parallel (matrix strategy)
2. Uses placeholder credentials from `opentofu/examples/ci-*.tfvars`
3. Runs `terraform plan` to validate resource generation logic
4. **Expected behavior**: Plans may fail at provider authentication, but this validates the configuration logic is sound
5. Exit code handling ensures workflow succeeds even with expected auth failures

**Key Features**:
- `fail-fast: false` - All scenarios run even if one fails
- Placeholder OCIDs and credentials prevent accidental resource creation
- Tests different combinations of variables
- Validates conditional logic (e.g., BYO vs. new resources)

### 3. Security Scanning (`verify-iac-security`)

**Purpose**: Identify security issues and best practice violations

**Tools**:
- **tfsec**: Terraform-specific security scanner
  - Checks for insecure configurations
  - Validates network security groups
  - Ensures encryption is enabled
  - Scans for AWS, Azure, GCP, and OCI-specific issues

**Note**: tfsec runs in `soft_fail: true` mode to avoid blocking PRs on warnings

### 4. Validation Summary (`verify-iac-summary`)

**Purpose**: Aggregate results and provide clear pass/fail status

**Dependencies**: Waits for all other jobs to complete

**Output**: Summary of all validation checks

## Variable Files Structure

### Production Files (NOT in git)

```
opentofu/
├── terraform.tfvars        # Your real credentials (NEVER commit)
├── private_key.pem         # Your OCI API key (NEVER commit)
└── *.auto.tfvars          # Additional variable files (NEVER commit)
```

### Example Files (IN git, safe to commit)

```
opentofu/examples/
├── README.md                        # Documentation
├── ci-vm-new-adb.tfvars            # VM with new ADB
├── ci-k8s-new-adb.tfvars           # Kubernetes with new ADB
├── ci-vm-byo-adb.tfvars            # VM with existing ADB
├── ci-k8s-byo-other-db.tfvars      # Kubernetes with other DB
└── ci-vm-arm-shape.tfvars          # VM with ARM compute
```

## .gitignore Configuration

The `.gitignore` file is configured to:

```gitignore
# Block all tfvars files (real credentials)
**/**.tfvars

# Allow example files (placeholder credentials only)
!opentofu/examples/*.tfvars

# Block private keys
**/*.pem

# Block terraform state and plans
**/terraform.tfstate*
**/*.tfplan*
```

## Running Tests Locally

### Option 1: Manual Validation

```bash
# Navigate to opentofu directory
cd opentofu/

# Initialize (no backend)
terraform init -backend=false

# Validate syntax
terraform validate

# Check formatting
terraform fmt -recursive -check

# Test a specific scenario
terraform plan -var-file=examples/ci-vm-new-adb.tfvars
```

### Option 2: Using act (GitHub Actions locally)

```bash
# Install act: https://github.com/nektos/act
brew install act

# Run all jobs
act pull_request

# Run specific job
act pull_request -j verify-iac-plans

# Run with specific scenario
act pull_request -j verify-iac-plans -matrix scenario:"VM + New ADB"
```

## Adding New Test Scenarios

To add a new deployment scenario:

1. **Create the variable file**:
   ```bash
   cd opentofu/examples/
   cp ci-vm-new-adb.tfvars ci-my-new-scenario.tfvars
   ```

2. **Edit with your scenario**:
   - Use placeholder OCIDs
   - Set appropriate infrastructure/database settings
   - Add comments explaining the scenario

3. **Update the workflow**:
   Edit `.github/workflows/opentofu.yml` and add to the matrix:
   ```yaml
   - name: "My New Scenario"
     tfvars: "examples/ci-my-new-scenario.tfvars"
     description: "Description of what this tests"
   ```

4. **Update documentation**:
   Add the scenario to `opentofu/examples/README.md`

5. **Test locally**:
   ```bash
   terraform plan -var-file=examples/ci-my-new-scenario.tfvars
   ```

6. **Commit and push**:
   ```bash
   git add opentofu/examples/ci-my-new-scenario.tfvars
   git add .github/workflows/opentofu.yml
   git add opentofu/examples/README.md
   git commit -m "Add new test scenario: My New Scenario"
   git push
   ```

## Workflow Triggers

The workflow runs on:

- **Pull Requests**: When opening, updating, or reopening non-draft PRs
- **Path Filters**: Only when changes affect:
  - `opentofu/**` (infrastructure code)
  - `tests/**` (test files)
  - `.github/workflows/opentofu.yml` (workflow itself)
- **Manual Dispatch**: Via GitHub Actions UI (useful for testing)

## Expected Results

### ✅ Success Criteria

- **Basic validation**: All syntax and formatting checks pass
- **Plan validation**: All scenarios execute without Terraform configuration errors
- **Security scanning**: No critical security issues (warnings are informational)

### ⚠️ Expected Warnings

- **Authentication errors**: Plans will fail at provider auth - this is expected and handled
- **Security warnings**: tfsec may flag policies - these are informational
- **Plan errors for fake resources**: Some data sources may fail - this validates error handling

### ❌ Failure Conditions

- **Syntax errors**: Invalid HCL syntax
- **Validation errors**: Missing required variables, invalid types
- **Formatting issues**: Code not formatted with `terraform fmt`
- **Schema violations**: Oracle Resource Manager schema validation failures

## Continuous Improvement

### Metrics to Track

- Time to run workflow (target: < 10 minutes)
- Number of scenarios covered (current: 5)
- Coverage of variable combinations
- Security issue trends

### Future Enhancements

- [ ] Add cost estimation with Infracost
- [ ] Generate Terraform docs automatically
- [ ] Add compliance scanning (OCI CIS Benchmark)
- [ ] Cache Terraform providers for faster runs
- [ ] Add PR comments with plan summaries
- [ ] Test BYO network scenarios
- [ ] Add GPU compute shape scenarios
- [ ] Test different regions
- [ ] Add module-specific tests

## Troubleshooting

### Workflow fails on `terraform init`

**Cause**: Provider version issues or network problems

**Solution**: Check `versions.tf` for provider version constraints

### Plan validation fails unexpectedly

**Cause**: Invalid variable combinations

**Solution**:
1. Run locally: `terraform plan -var-file=examples/ci-<scenario>.tfvars`
2. Check logs for specific error
3. Validate variable file against `variables.tf`

### Security scan fails

**Cause**: New security policy violations

**Solution**:
1. Review tfsec output
2. Determine if it's a false positive
3. Add exception if needed or fix the issue
4. Document decision in PR

### Matrix scenario not running

**Cause**: YAML syntax error in matrix definition

**Solution**: Validate YAML syntax, ensure proper indentation

## Resources

- [OpenTofu Documentation](https://opentofu.org/docs/)
- [Terraform Best Practices](https://www.terraform-best-practices.com/)
- [tfsec Rules](https://aquasecurity.github.io/tfsec/)
- [OCI Terraform Provider](https://registry.terraform.io/providers/oracle/oci/latest/docs)
- [GitHub Actions Matrix Strategy](https://docs.github.com/en/actions/using-jobs/using-a-matrix-for-your-jobs)

## Support

For issues or questions:

1. Check this documentation
2. Review workflow logs in GitHub Actions
3. Test locally with example files
4. Open an issue with:
   - Scenario being tested
   - Error message
   - Steps to reproduce
