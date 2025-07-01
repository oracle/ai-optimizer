"""
Copyright (c) 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore kubeconfig

import subprocess
import argparse
import os
import sys

# --- Constants ---
HELM_NAME = "ai-optimizer"
HELM_REPO = "https://oracle-samples.github.io/ai-optimizer/helm"
STAGE_PATH = os.path.join(os.path.dirname(__file__), "stage")
os.environ["KUBECONFIG"] = os.path.join(STAGE_PATH, "kubeconfig")


# --- Utility Functions ---
def run_cmd(cmd, capture_output=True):
    """Run a shell command and return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=True,
            check=False,  # Explicitly set check=False
        )
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""
        return stdout, stderr, result.returncode
    except subprocess.SubprocessError as e:
        return "", str(e), 1

# --- Core Functionalities ---
def helm_repo_add_if_missing():
    """Add Helm repo if not already added."""
    print(f"➕ Adding Helm repo '{HELM_NAME}'...")
    stdout, stderr, rc = run_cmd(["helm", "repo", "add", HELM_NAME, HELM_REPO], capture_output=False)
    if rc != 0:
        print(f"❌ Failed to add repo:\n{stderr}")
        sys.exit(1)
    print(f"Add Helm Repo: {stdout}")

    print("⬆️ Checking for Helm updates...")
    stdout, stderr, rc = run_cmd(["helm", "repo", "update"], capture_output=False)
    if rc != 0:
        print(f"❌ Failed to update repos:\n{stderr}")
        sys.exit(1)
    print(f"Update Helm Repo: {stdout}")
    print(f"✅ Repo '{HELM_NAME}' added and updated.\n")


def apply_helm_chart(release_name, namespace):
    """Install or upgrade a Helm release."""
    values_path = os.path.join(STAGE_PATH, "helm-values.yaml")
    if not os.path.isfile(values_path):
        print(f"⚠️ Values file not found: {values_path}")
        sys.exit(1)

    helm_repo_add_if_missing()

    cmd = [
        "helm",
        "upgrade",
        "--install",
        release_name,
        f"{HELM_NAME}/{HELM_NAME}",
        "--namespace",
        namespace,
          "--values",
        values_path,
    ]

    print(f"🚀 Applying Helm chart '{HELM_NAME}' to namespace '{namespace}'...")
    stdout, stderr, rc = run_cmd(cmd)
    if rc != 0:
        print(f"❌ Failed to apply Helm chart:\n{stderr}")
        sys.exit(1)

    print("✅ Helm chart applied:")
    print(f"Apply Helm Chart: {stdout}")

def apply_manifest():
    """Apply a Kubernetes manifest from the stage path."""
    manifest_path = os.path.join(STAGE_PATH, "k8s-manifest.yaml")
    if not os.path.isfile(manifest_path):
        print(f"⚠️ Manifest not found: {manifest_path}")
        return
    print("🚀 Applying Kubernetes manifest: k8s-manifest.yaml")
    run_cmd(["kubectl", "apply", "-f", manifest_path], capture_output=False)
    print("✅ Manifest applied.\n")


# --- Entry Point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply a Helm chart and a Kubernetes manifest.")
    parser.add_argument("release_name", help="Helm release name")
    parser.add_argument("namespace", help="Kubernetes namespace")
    args = parser.parse_args()

    apply_manifest()
    apply_helm_chart(args.release_name, args.namespace)
