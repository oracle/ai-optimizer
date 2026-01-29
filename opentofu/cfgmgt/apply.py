"""
Copyright (c) 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore kubeconfig obaas prereqs

import subprocess
import argparse
import os
import sys
import time

# --- Constants ---
STAGE_PATH = os.path.join(os.path.dirname(__file__), "stage")
os.environ["KUBECONFIG"] = os.path.join(STAGE_PATH, "kubeconfig")

# --- Helm Charts Configuration ---
HELM_CHARTS = [
    {
        "name": "ai-optimizer",
        "chart_ref": "ai-optimizer/ai-optimizer",
        "repo_url": "https://oracle.github.io/ai-optimizer/helm",
        "repo_name": "ai-optimizer",
        "values_file": "ai-optimizer-values.yaml",
    },
]


# --- Utility Functions ---
def mod_kubeconfig(private_endpoint: str = None):
    """Modify Kubeconfig with private endpoint if applicable"""
    if not private_endpoint:
        return

    with open(os.environ["KUBECONFIG"], "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    with open(os.environ["KUBECONFIG"], "w", encoding="utf-8") as f:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("server:"):
                # Preserve indentation
                indent = line[: len(line) - len(line.lstrip())]
                f.write(f"{indent}server: https://{private_endpoint}:6443\n")
            elif stripped.startswith("certificate-authority-data:"):
                # Preserve indentation
                indent = line[: len(line) - len(line.lstrip())]
                f.write(f"{indent}insecure-skip-tls-verify: true\n")
            else:
                f.write(line + "\n")

    print("✅ Modified kubeconfig with private endpoint.\n")


def run_cmd(cmd, capture_output=True):
    """Generic subprocess execution"""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=True,
            check=False,
        )
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""
        return stdout, stderr, result.returncode
    except subprocess.SubprocessError as e:
        return "", str(e), 1


def retry(func, retries=5, delay=15):
    """Retry a function with given arguments on failure using exponential backoff (x2)."""
    current_delay = delay
    for attempt in range(1, retries + 1):
        print(f"🔁 Attempt {attempt}/{retries}")
        if func():
            return True
        if attempt < retries:
            print(f"⏳ Retrying in {current_delay} seconds...")
            time.sleep(current_delay)
            current_delay *= 2  # Exponential backoff: double the delay
    print("🚨 Maximum retries reached. Exiting.")
    sys.exit(1)


# --- Core Functionalities ---
def helm_repo_add_if_missing(repos_to_add):
    """Add/Update Helm Repos for charts that need remote repositories"""
    if not repos_to_add:
        print("ℹ️ No remote Helm repos to add.\n")
        return

    for repo_name, repo_url in repos_to_add.items():
        print(f"➕ Adding Helm repo '{repo_name}'...")
        _, stderr, rc = run_cmd(["helm", "repo", "add", repo_name, repo_url], capture_output=False)
        if rc != 0:
            print(f"❌ Failed to add repo '{repo_name}':\n{stderr}")
            sys.exit(1)

    print("⬆️ Checking for Helm updates...")
    _, stderr, rc = run_cmd(["helm", "repo", "update"], capture_output=False)
    if rc != 0:
        print(f"❌ Failed to update repos:\n{stderr}")
        sys.exit(1)
    print("✅ Repos added and updated.\n")


def apply_single_helm_chart_inner(chart_config, values_file, namespace, optimizer_version=None):
    """Apply a single Helm Chart with its values file"""
    chart_name = chart_config["name"]
    chart_ref = chart_config["chart_ref"]
    values_path = os.path.join(STAGE_PATH, values_file)

    cmd = [
        "helm",
        "upgrade",
        "--install",
        chart_name,
        chart_ref,
        "--namespace",
        namespace,
        "--values",
        values_path,
    ]

    # Add version flag if this is the ai-optimizer chart and optimizer_version is "Experimental"
    if chart_name == "ai-optimizer" and optimizer_version == "Experimental":
        cmd.extend(["--version", "0.0.0"])
        print("🔬 Using Experimental version (0.0.0)")
    elif chart_name == "ai-optimizer":
        print("✅ Using latest Stable release")

    print(f"🚀 Applying Helm chart '{chart_name}' to namespace '{namespace}'...")
    print(f"📄 Using values file: {values_file}")
    stdout, stderr, rc = run_cmd(cmd)
    if rc == 0:
        print(f"✅ Helm chart '{chart_name}' applied successfully.")
        if stdout:
            print(f"   {stdout}")
        return True

    print(f"❌ Failed to apply Helm chart '{chart_name}':\n{stderr}")
    return False


def apply_single_helm_chart(chart_config, values_file, namespace, optimizer_version=None):
    """Retry Enabled - Apply a single Helm Chart"""
    retry(lambda: apply_single_helm_chart_inner(chart_config, values_file, namespace, optimizer_version))


def apply_all_helm_charts(namespace, optimizer_version=None):
    """Apply Helm charts in HELM_CHARTS order if their values files exist"""
    # Match charts to values files (iterate through HELM_CHARTS to preserve order)
    charts_to_apply = []
    repos_to_add = {}

    for chart_config in HELM_CHARTS:
        values_filename = chart_config["values_file"]
        values_path = os.path.join(STAGE_PATH, values_filename)

        # Check if values file exists
        if os.path.isfile(values_path):
            print(f"✓ Found values file for '{chart_config['name']}': {values_filename}")
            charts_to_apply.append((chart_config, values_filename))
            # Collect remote repos that need to be added
            if chart_config["repo_url"] is not None:
                repos_to_add[chart_config["repo_name"]] = chart_config["repo_url"]
        else:
            print(f"⊘ Skipping '{chart_config['name']}': values file not found ({values_filename})")

    if not charts_to_apply:
        print("\n⚠️ No charts to apply (no matching values files found).\n")
        return

    print()  # Blank line after file detection

    # Add all required Helm repos
    helm_repo_add_if_missing(repos_to_add)

    # Apply each chart in order
    print(f"📦 Applying {len(charts_to_apply)} Helm chart(s) in order...\n")
    for chart_config, values_file in charts_to_apply:
        apply_single_helm_chart(chart_config, values_file, namespace, optimizer_version)
        print()  # Add blank line between charts

    print("✅ All Helm charts applied successfully.\n")


def apply_manifest_inner(namespace):
    """Apply Manifest"""
    manifest_path = os.path.join(STAGE_PATH, "k8s-manifest.yaml")
    if not os.path.isfile(manifest_path):
        print(f"⚠️ Manifest not found: {manifest_path}")
        return False

    # Delete existing Jobs with the same name to allow recreation
    # Jobs are immutable and cannot be updated, only replaced
    print("🗑️ Checking for existing buildkit Job...")
    stdout, _, _ = run_cmd(
        ["kubectl", "get", "job", "optimizer-buildkit", "-n", namespace, "-o", "name"], capture_output=True
    )
    if stdout:
        print(f"🗑️ Deleting existing optimizer-buildkit Job in namespace '{namespace}'...")
        run_cmd(
            ["kubectl", "delete", "job", "optimizer-buildkit", "-n", namespace, "--ignore-not-found=true"],
            capture_output=False,
        )
        time.sleep(2)  # Wait for deletion to complete

    print("🚀 Applying Kubernetes manifest: k8s-manifest.yaml")
    _, stderr, rc = run_cmd(["kubectl", "apply", "-f", manifest_path], capture_output=False)
    if rc == 0:
        print("✅ Manifest applied.\n")
        return True

    print(f"❌ Failed to apply manifest:\n{stderr}")
    return False


def apply_manifest(namespace):
    """Retry Enabled Add/Update Manifest"""
    retry(lambda: apply_manifest_inner(namespace))


def patch_oracle_operator():
    """Patch Oracle Database Operator deployment and wait for it to be ready"""
    print("🔧 Patching oracle-database-operator deployment...")
    patch_json = (
        '[{"op": "replace", "path": '
        '"/spec/template/spec/containers/0/securityContext/readOnlyRootFilesystem", '
        '"value": false}]'
    )
    cmd = [
        "kubectl",
        "-n",
        "oracle-database-operator-system",
        "patch",
        "deployment",
        "oracle-database-operator-controller-manager",
        "--type",
        "json",
        "-p",
        patch_json,
    ]
    _, stderr, rc = run_cmd(cmd, capture_output=False)
    if rc != 0:
        print(f"❌ Failed to patch operator:\n{stderr}")
        sys.exit(1)

    print("✅ Oracle operator patched.\n")

    # Wait for operator to be ready after patching
    print("⏳ Waiting for Oracle Database Operator to be ready...")
    wait_cmd = [
        "kubectl",
        "wait",
        "--for=condition=Available",
        "--timeout=300s",
        "-n",
        "oracle-database-operator-system",
        "deployment/oracle-database-operator-controller-manager",
    ]
    _, stderr, rc = run_cmd(wait_cmd, capture_output=False)
    if rc != 0:
        print(f"❌ Operator readiness check failed:\n{stderr}")
        sys.exit(1)

    print("✅ Oracle Database Operator is ready.\n")
    # Additional wait to ensure webhook is fully operational
    print("⏳ Waiting an additional 30 seconds for webhook stabilization...")
    time.sleep(30)


# --- Entry Point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply a Helm chart and a Kubernetes manifest.")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--private_endpoint", nargs="?", const=None, default=None, help="Kubernetes Private Endpoint")
    parser.add_argument(
        "--optimizer_version",
        choices=["Stable", "Experimental"],
        default="Stable",
        help="Optimizer version (Stable or Experimental)",
    )
    args = parser.parse_args()

    mod_kubeconfig(args.private_endpoint)
    apply_manifest(args.namespace)
    patch_oracle_operator()
    apply_all_helm_charts(args.namespace, args.optimizer_version)
