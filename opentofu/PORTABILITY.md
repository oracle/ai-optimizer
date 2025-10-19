# OpenTofu Directory Portability Guide

This document explains how the `opentofu/` directory is designed to be portable and can be copied to other projects while maintaining proper `.gitignore` behavior.

## Design Philosophy

The `opentofu/` directory is **self-contained and portable** because:

1. ✅ It has its own `.gitignore` that works standalone
2. ✅ It includes example variable files for quick start
3. ✅ All documentation is included in the directory
4. ✅ CI/CD configurations are portable

This design allows the infrastructure code to be:
- Copied to other projects
- Distributed as a standalone package
- Used as a Git submodule
- Included in release artifacts

## Dual .gitignore Strategy

### Why Two .gitignore Files?

```
ai-optimizer/
├── .gitignore                    # Root - for this project
└── opentofu/
    ├── .gitignore                # Local - for portability
    ├── examples/
    │   └── *.tfvars              # Safe to commit
    └── terraform.tfvars          # IGNORED (real credentials)
```

**Root `.gitignore`** (`ai-optimizer/.gitignore`):
- Applies to the entire project
- Includes project-specific exclusions
- Has exception for `opentofu/examples/*.tfvars`

**Local `.gitignore`** (`ai-optimizer/opentofu/.gitignore`):
- Applies when `opentofu/` is copied elsewhere
- Works standalone in new repositories
- Has same exception for `examples/*.tfvars`

### How They Work Together

When in the original repo:
```
ai-optimizer/.gitignore:        **/**.tfvars           (blocks all)
ai-optimizer/.gitignore:        !opentofu/examples/*.tfvars  (allows examples)
opentofu/.gitignore:            **/**.tfvars           (blocks all)
opentofu/.gitignore:            !examples/*.tfvars     (allows examples)
```

Both `.gitignore` files have the **same rules**, ensuring consistent behavior whether the directory is:
- Part of the original repo
- Copied to a new repo
- Used as a submodule

## Portability Testing

### Test 1: In Original Repo

```bash
cd ai-optimizer/

# Example files are tracked
git status opentofu/examples/
# Shows: ci-*.tfvars files as untracked/modified

# Real credentials are ignored
echo "secret" > opentofu/terraform.tfvars
git status opentofu/terraform.tfvars
# Shows: nothing (file is ignored)
```

### Test 2: Copied to New Repo

```bash
# Create new repo
mkdir my-new-project && cd my-new-project
git init

# Copy opentofu directory
cp -r /path/to/ai-optimizer/opentofu .

# Add to git
git add opentofu/

# Check what's tracked
git status
# Shows: examples/*.tfvars are staged
# Shows: .gitignore is staged
# Does NOT show: terraform.tfvars (if it exists)

# Create real credentials
echo "secret" > opentofu/terraform.tfvars
git status
# Shows: nothing (terraform.tfvars is ignored by opentofu/.gitignore)
```

### Test 3: As Git Submodule

```bash
cd my-project/
git submodule add https://github.com/oracle/ai-optimizer.git
cd ai-optimizer/opentofu/

# The local .gitignore still works
cp examples/ci-vm-new-adb.tfvars terraform.tfvars
# Edit with real credentials
git status
# Shows: nothing (terraform.tfvars is ignored)
```

## Files Tracked vs Ignored

### ✅ Always Tracked (Safe to Commit)

```
opentofu/
├── .gitignore                   ✅ Safe
├── README.md                    ✅ Safe
├── TESTING.md                   ✅ Safe
├── PORTABILITY.md               ✅ Safe
├── *.tf                         ✅ Safe (infrastructure code)
├── modules/**/*.tf              ✅ Safe (module code)
├── cfgmgt/**/*.py              ✅ Safe (scripts)
└── examples/
    ├── README.md                ✅ Safe
    └── *.tfvars                 ✅ Safe (placeholder credentials)
```

### ❌ Always Ignored (Never Commit)

```
opentofu/
├── terraform.tfvars             ❌ IGNORED (real credentials)
├── *.auto.tfvars                ❌ IGNORED (real credentials)
├── private_key.pem              ❌ IGNORED (secret keys)
├── .terraform/                  ❌ IGNORED (provider cache)
├── .terraform.lock.hcl          ❌ IGNORED (lock file)
├── terraform.tfstate            ❌ IGNORED (state file)
├── terraform.tfstate.backup     ❌ IGNORED (state backup)
└── *.tfplan                     ❌ IGNORED (plan output)
```

## .gitignore File Contents

### Root `.gitignore` (Excerpt)

```gitignore
# Ignore all tfvars files (contain credentials)
**/**.tfvars

# But allow example tfvars files for CI/CD testing (safe, no real credentials)
!opentofu/examples/*.tfvars

# Terraform/OpenTofu state and cache
**/.terraform*
**/terraform.tfstate*
**/*.tfplan
**/*.tfplan.out
```

### Local `opentofu/.gitignore`

```gitignore
##############################################################################
# IaC
##############################################################################
# Ignore all tfvars files (contain credentials)
**/**.tfvars
# But allow example tfvars files for CI/CD testing (safe, no real credentials)
!examples/*.tfvars

# Terraform/OpenTofu state and cache
**/.terraform*
**/terraform.tfstate*
**/*.tfplan
**/*.tfplan.out

# Private keys and sensitive files
**/*.pem

# Stage directory
**/stage/*.*
**/stage/kubeconfig
```

## Using in Different Scenarios

### Scenario 1: Copy to Another Project

```bash
# 1. Copy the directory
cp -r opentofu/ /path/to/my-project/

# 2. Navigate to it
cd /path/to/my-project/opentofu/

# 3. Use an example as template
cp examples/ci-vm-new-adb.tfvars terraform.tfvars

# 4. Edit with real credentials
vim terraform.tfvars

# 5. The local .gitignore protects your credentials
git add .
# terraform.tfvars will NOT be added (ignored)
# examples/*.tfvars WILL be added (allowed)
```

### Scenario 2: Package for Distribution

```bash
# Create a zip with examples but without credentials
cd opentofu/
zip -r ai-optimizer-iac.zip . \
  -x "terraform.tfvars" \
  -x "*.auto.tfvars" \
  -x "*.pem" \
  -x ".terraform*" \
  -x "terraform.tfstate*" \
  -x "*.tfplan*" \
  -x "cfgmgt/stage/*.*"

# The zip includes:
# ✅ All .tf files
# ✅ All documentation
# ✅ examples/*.tfvars
# ✅ .gitignore
# ❌ No credentials
# ❌ No state files
# ❌ No cache
```

### Scenario 3: Fork and Customize

```bash
# 1. Fork the repo
git clone https://github.com/your-fork/ai-optimizer.git
cd ai-optimizer/opentofu/

# 2. Create your own examples (safe to commit)
cp examples/ci-vm-new-adb.tfvars examples/my-company-prod.tfvars
# Edit with PLACEHOLDER values (not real credentials)
vim examples/my-company-prod.tfvars

# 3. This is safe to commit
git add examples/my-company-prod.tfvars
git commit -m "Add my-company-prod example"

# 4. For real deployments, use terraform.tfvars (ignored)
cp examples/my-company-prod.tfvars terraform.tfvars
# Edit with REAL credentials
vim terraform.tfvars
# This will NOT be tracked by git
```

## Best Practices

### ✅ DO

- ✅ Keep example files with placeholder credentials
- ✅ Document all variables in examples
- ✅ Test portability before releasing
- ✅ Include .gitignore in the directory
- ✅ Keep documentation self-contained

### ❌ DON'T

- ❌ Commit real credentials to examples
- ❌ Remove the local .gitignore
- ❌ Hard-code credentials in .tf files
- ❌ Commit .tfstate files
- ❌ Commit .terraform directory

## Verification Commands

### Check What Git Sees

```bash
# See what would be added
git add -n opentofu/

# Check ignore rules for a file
git check-ignore -v opentofu/terraform.tfvars
# Should show: .gitignore:X:**/**.tfvars

git check-ignore -v opentofu/examples/ci-vm-new-adb.tfvars
# Should show: .gitignore:Y:!examples/*.tfvars (negated, allowed)
```

### Test in Clean Repo

```bash
# Create test repo
mkdir test-portable && cd test-portable
git init

# Copy opentofu
cp -r /path/to/opentofu .

# Create fake credentials
echo "secret" > opentofu/terraform.tfvars

# Add everything
git add .

# Verify terraform.tfvars is NOT staged
git status | grep terraform.tfvars
# Should return nothing

# Verify examples ARE staged
git status | grep examples
# Should show examples/*.tfvars as new files
```

## Troubleshooting

### Problem: Example files not tracked

**Symptom:**
```bash
git status opentofu/examples/
# Shows: nothing
```

**Solution:**
Check .gitignore has negation rule:
```bash
cat opentofu/.gitignore | grep examples
# Should show: !examples/*.tfvars
```

### Problem: Real credentials being tracked

**Symptom:**
```bash
git status
# Shows: terraform.tfvars as untracked
```

**Solution:**
Ensure .gitignore has block rule:
```bash
cat opentofu/.gitignore | grep tfvars
# Should show: **/**.tfvars (before the ! rule)
```

### Problem: Portability not working

**Symptom:**
After copying to new repo, credentials are tracked.

**Solution:**
1. Verify local .gitignore exists:
   ```bash
   ls opentofu/.gitignore
   ```

2. Verify it was copied:
   ```bash
   cat opentofu/.gitignore
   ```

3. Re-add with force:
   ```bash
   git rm --cached opentofu/terraform.tfvars
   git add opentofu/.gitignore
   ```

## CI/CD Integration

The dual .gitignore strategy works seamlessly with CI/CD:

```yaml
# GitHub Actions workflow
- name: Checkout Code
  uses: actions/checkout@v4

- name: Test with example variables
  working-directory: ./opentofu
  run: |
    # Uses examples/*.tfvars (tracked in git)
    terraform plan -var-file=examples/ci-vm-new-adb.tfvars
    # Works because examples are in the repo!
```

## Summary

The dual `.gitignore` approach provides:

✅ **Portability** - Works when copied to other projects
✅ **Security** - Never commits real credentials
✅ **Convenience** - Example files always available
✅ **CI/CD Ready** - Test scenarios in version control
✅ **Consistency** - Same rules in original and copied repos

This design makes the `opentofu/` directory truly portable and safe to share!
