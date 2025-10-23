# OpenTofu Infrastructure Testing Guide

## Overview

This document outlines the **mandatory testing requirements** for OpenTofu infrastructure code changes.

**CRITICAL:** GitHub Actions CI validates **syntax and formatting only**. It does NOT validate infrastructure logic, resource creation, or OCI API interactions. Manual testing with real OCI credentials is **required** before merging any PR that modifies `.tf` files.

---

## Why Manual Testing is Required

The OpenTofu/Terraform OCI provider requires authentication to OCI APIs before generating execution plans. Without real credentials:

- ❌ OCI provider resources are not validated (~95% of infrastructure)
- ❌ Data source queries fail (no API access)
- ❌ Conditional resource logic is not evaluated
- ❌ Computed attributes remain unknown
- ❌ Resource dependencies cannot be resolved

---

## Manual Testing Requirements

### Required Before PR Approval

**Every PR that modifies `.tf` files MUST be tested with real OCI credentials.**

#### Testing Steps:

1. **Setup OCI CLI** (one-time)

   ```bash
   oci setup config
   ```

   This creates `~/.oci/config` with your OCI credentials.

2. **Run Tests**

   ```bash
   cd opentofu/
   examples/manual-test.sh
   ```

   The script will:
   - Load credentials from `~/.oci/config`
   - Run `tofu init` and `tofu plan` on all testable examples
   - Display plan summary for each example (e.g., "Plan: 53 to add, 0 to change, 0 to destroy")
   - Stop on first failure

3. **Verify Output**

   Each test should show:
   - ✅ PASSED status
   - Resource count of ~30-50 (NOT 3-5)
   - Example: `✅ Plan: 53 to add, 0 to change, 0 to destroy.`

   If any test fails, the script will show how to re-run with full output.

4. **Document Testing in PR**

   Add a comment to the PR:
   ```markdown
   ## Manual Testing Completed

   Ran `examples/manual-test.sh` successfully.
   All examples validated with real OCI credentials.
   ```

---

## Testing Best Practices

### 1. Use a Dedicated Test Compartment
Create a separate OCI compartment for infrastructure testing to avoid impacting production resources.

### 2. Review the Plan Summary
The test script shows the plan summary for each example:
- **30-50 resources** indicates full validation (✅ good)
- **3-5 resources** indicates failed validation (❌ bad - missing OCI auth or data sources)

### 3. Test Plan AND Apply
For major changes, consider running `tofu apply` in a test compartment to validate:
- Resource creation succeeds
- Dependencies are resolved correctly
- Outputs are generated as expected
- Resources can be destroyed cleanly

---

## PR Approval Checklist

Before approving a PR that modifies OpenTofu code:

- [ ] GitHub Actions CI passed (syntax, formatting, schema, security)
- [ ] Author ran `examples/manual-test.sh` with real OCI credentials
- [ ] PR includes comment confirming manual testing completed
- [ ] All test examples passed with ~30-50 resources
- [ ] Code review identified no obvious issues
