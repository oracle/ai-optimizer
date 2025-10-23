"""
Copyright (c) 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore kubeconfig

import subprocess
import argparse
import os
import sys
import time

# --- Constants ---
STAGE_PATH = os.path.join(os.path.dirname(__file__), "stage")
os.environ["KUBECONFIG"] = os.path.join(STAGE_PATH, "kubeconfig")

# --- Helm Charts ---
OPTIMIZER_HELM_NAME = "ai-optimizer"
OPTIMIZER_HELM_REPO = "https://oracle.github.io/ai-optimizer/helm"

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
def helm_repo_add_if_missing():
    """Add/Update Helm Repo"""
    print(f"➕ Adding Helm repo '{OPTIMIZER_HELM_NAME}'...")
    _, stderr, rc = run_cmd(["helm", "repo", "add", OPTIMIZER_HELM_NAME, OPTIMIZER_HELM_REPO], capture_output=False)
    if rc != 0:
        print(f"❌ Failed to add repo:\n{stderr}")
        sys.exit(1)

    print("⬆️ Checking for Helm updates...")
    _, stderr, rc = run_cmd(["helm", "repo", "update"], capture_output=False)
    if rc != 0:
        print(f"❌ Failed to update repos:\n{stderr}")
        sys.exit(1)
    print(f"✅ Repo '{OPTIMIZER_HELM_NAME}' added and updated.\n")


def apply_helm_chart_inner(release_name, namespace, optimizer_version=None):
    """Apply Helm Chart"""
    # Find all *-values.yaml files in the stage directory
    values_files = [
        f for f in os.listdir(STAGE_PATH)
        if f.endswith("-values.yaml") and os.path.isfile(os.path.join(STAGE_PATH, f))
    ]

    if not values_files:
        print(f"⚠️ No values files (*-values.yaml) found in: {STAGE_PATH}")
        print("ℹ️ Skipping Helm chart application.\n")
        return True  # Return True to indicate this is not a retriable failure

    helm_repo_add_if_missing()

    # Build helm command with all values files
    cmd = [
        "helm",
        "upgrade",
        "--install",
        release_name,
        f"{OPTIMIZER_HELM_NAME}/{OPTIMIZER_HELM_NAME}",
        "--namespace",
        namespace,
    ]

    # Add version flag if optimizer_version is "Experimental"
    if optimizer_version == "Experimental":
        cmd.extend(["--version", "0.0.0"])
        print("🔬 Using Experimental version (0.0.0)")
    else:
        print("✅ Using latest Stable release")

    # Add each values file to the command
    for values_file in sorted(values_files):
        values_path = os.path.join(STAGE_PATH, values_file)
        cmd.extend(["--values", values_path])
        print(f"📄 Using values file: {values_file}")

    print(f"🚀 Applying Helm chart '{OPTIMIZER_HELM_NAME}' to namespace '{namespace}'...")
    stdout, stderr, rc = run_cmd(cmd)
    if rc == 0:
        print("✅ Helm chart applied:")
        print(f"Apply Helm Chart: {stdout}")
        return True

    print(f"❌ Failed to apply Helm chart:\n{stderr}")
    return False


def apply_helm_chart(release_name, namespace, optimizer_version=None):
    """Retry Enabled Add/Update Helm Chart"""
    retry(lambda: apply_helm_chart_inner(release_name, namespace, optimizer_version))


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


def patch_oracle_operator_inner():
    """Patch Oracle Database Operator deployment to disable readOnlyRootFilesystem"""
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
    if rc == 0:
        print("✅ Oracle operator patched.\n")
        return True

    print(f"❌ Failed to patch operator:\n{stderr}")
    return False


def patch_oracle_operator():
    """Retry Enabled Patch Oracle Operator"""
    retry(patch_oracle_operator_inner)


# --- Entry Point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply a Helm chart and a Kubernetes manifest.")
    parser.add_argument("release_name", help="Helm release name")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--private_endpoint", nargs="?", const=None, default=None, help="Kubernetes Private Endpoint")
    parser.add_argument(
        "--optimizer_version",
        choices=["Stable", "Experimental"],
        default="Stable",
        help="Optimizer version (Stable or Experimental)"
    )
    args = parser.parse_args()

    mod_kubeconfig(args.private_endpoint)
    apply_manifest(args.namespace)
    patch_oracle_operator()
    apply_helm_chart(args.release_name, args.namespace, args.optimizer_version)
