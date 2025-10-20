#!/bin/bash
# Test script to validate OpenTofu infrastructure with real OCI credentials
# Usage: examples/test.sh [profile_name]

set -euo pipefail

# Navigate to opentofu root
cd "$(dirname "$(dirname "$0")")" || exit 1

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

    if plan_output=$(tofu plan -var-file="$example" 2>&1); then
        plan_summary=$(echo "$plan_output" | grep -i "plan:" | tail -1 | sed 's/^[[:space:]]*//')
        echo "  ✅ ${plan_summary:-PASSED}"
    else
        echo "  ❌ FAILED"
        echo ""
        echo "Re-run: tofu plan -var-file=$example"
        exit 1
    fi
done

echo ""
echo "✅ All tests passed"
