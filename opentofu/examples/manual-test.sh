#!/bin/bash
# Test script to validate OpenTofu infrastructure with real OCI credentials
# Usage: examples/test.sh [profile_name]

set -euo pipefail

# Navigate to opentofu root
cd "$(dirname "$(dirname "$0")")" || exit 1

# Check for tofu or terraform in PATH
if command -v tofu &> /dev/null; then
    TF_CMD="tofu"
elif command -v terraform &> /dev/null; then
    TF_CMD="terraform"
else
    echo "Error: Neither 'tofu' nor 'terraform' found in PATH" >&2
    exit 1
fi

echo "Using command: $TF_CMD"
echo ""

PROFILE="${1:-DEFAULT}"
OCI_CONFIG="${OCI_CONFIG_FILE:-$HOME/.oci/config}"

[ -f "$OCI_CONFIG" ] || { echo "Error: OCI config not found at $OCI_CONFIG" >&2; exit 1; }

# Parse OCI config file
SECTION_FOUND=false
while IFS='=' read -r key value; do
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)

    # Check for section header
    if [ "${key#\[}" != "$key" ]; then
        [ "$(echo "$key" | tr -d '[]')" = "$PROFILE" ] && SECTION_FOUND=true || SECTION_FOUND=false
        continue
    fi

    # Extract credentials from matching section
    [ "$SECTION_FOUND" = "true" ] || continue
    case "$key" in
        user)        export TF_VAR_user_ocid="$value" ;;
        tenancy)     export TF_VAR_tenancy_ocid="$value" ;;
        region)      export TF_VAR_region="$value" ;;
        fingerprint) export TF_VAR_fingerprint="$value" ;;
        key_file)    export TF_VAR_private_key_path="$value" ;;
    esac
done < "$OCI_CONFIG"

# Verify credentials loaded
[ -n "${TF_VAR_user_ocid:-}" ] && [ -n "${TF_VAR_tenancy_ocid:-}" ] && [ -n "${TF_VAR_region:-}" ] || \
    { echo "Error: Failed to load credentials from profile [$PROFILE]" >&2; exit 1; }

export TF_VAR_compartment_ocid="$TF_VAR_tenancy_ocid"

echo "✅ OCI credentials loaded (Profile: $PROFILE, Region: $TF_VAR_region)"
echo ""

# Pre-flight checks: format and validate
echo "Running pre-flight checks..."
echo ""

echo "1. Formatting code with '$TF_CMD fmt --recursive'..."
if $TF_CMD fmt --recursive > /dev/null; then
    echo "  ✅ Format check passed"
else
    echo "  ❌ Format check failed"
    exit 1
fi

echo "2. Validating configuration with '$TF_CMD validate'..."
if $TF_CMD validate > /dev/null 2>&1; then
    echo "  ✅ Validation passed"
else
    echo "  ❌ Validation failed"
    echo ""
    echo "Re-run: $TF_CMD validate"
    exit 1
fi

echo ""

# Check for existing deployed resources
if [ -f "terraform.tfstate" ] && [ -s "terraform.tfstate" ]; then
    echo "Checking for deployed resources..."

    # Use terraform state list to check if there are any managed resources
    if resource_count=$($TF_CMD state list 2>/dev/null | wc -l | xargs); then
        if [ "$resource_count" -gt 0 ]; then
            echo "❌ ERROR: Found $resource_count deployed resource(s) in the state"
            echo ""
            echo "This test script requires a clean state to test multiple configurations."
            echo "Please destroy existing resources first:"
            echo ""
            echo "  $TF_CMD destroy -auto-approve"
            echo ""
            exit 1
        else
            echo "  ✅ State file exists but no resources are deployed (likely from previous destroy)"
        fi
    fi
fi

# Run tests
EXAMPLES=(
    examples/vm-new-adb.tfvars
    examples/k8s-new-adb.tfvars
    examples/vm-arm-shape.tfvars
    examples/vm-byo-other-db.tfvars
    examples/k8s-byo-other-db.tfvars
)

for example in "${EXAMPLES[@]}"; do
    echo "Testing $example..."

    if plan_output=$($TF_CMD plan -var-file="$example" 2>&1); then
        plan_summary=$(echo "$plan_output" | grep -i "plan:" | tail -1 | sed 's/^[[:space:]]*//')
        echo "  ✅ ${plan_summary:-PASSED}"
    else
        echo "  ❌ FAILED"
        echo ""
        echo "Error output:"
        echo "$plan_output" | tail -20
        echo ""
        echo "Re-run: $TF_CMD plan -var-file=$example"
        exit 1
    fi
done

echo ""
echo "✅ All tests passed"
