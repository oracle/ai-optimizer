"""
Copyright (c) 2025, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore kubeconfig obaas prereqs

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

# --- Constants ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STAGE_PATH = os.path.join(SCRIPT_DIR, "stage")
LOCAL_HELM_DIR = os.path.join(SCRIPT_DIR, "helm")
os.environ["KUBECONFIG"] = os.path.join(STAGE_PATH, "kubeconfig")

ORACLE_OPERATOR_NS = "oracle-database-operator-system"
ORACLE_OPERATOR_DEPLOYMENT = "oracle-database-operator-controller-manager"
ORACLE_OPERATOR_CRB = "oracle-database-operator-manager-clusterrolebinding"
ORACLE_OPERATOR_CR = "oracle-database-operator-manager-role"

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
def mod_kubeconfig(private_endpoint: str | None = None):
    """Modify Kubeconfig with private endpoint if applicable"""
    if not private_endpoint:
        return

    kubeconfig_path = os.environ["KUBECONFIG"]
    with open(kubeconfig_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    with open(kubeconfig_path, "w", encoding="utf-8") as f:
        for line in lines:
            stripped = line.strip()
            indent = line[: len(line) - len(line.lstrip())]

            if stripped.startswith("server:"):
                # Preserve indentation
                indent = line[: len(line) - len(line.lstrip())]
                f.write(f"{indent}server: https://{private_endpoint}:6443\n")
            elif stripped.startswith("certificate-authority-data:"):
                indent = line[: len(line) - len(line.lstrip())]
                f.write(f"{indent}insecure-skip-tls-verify: true\n")
            else:
                f.write(line + "\n")

    print("✅ Modified kubeconfig with private endpoint.\n")


def run_cmd(cmd, capture_output=True):
    """Execute a shell command and return stdout, stderr, and return code"""
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
    """Retry a function on failure using exponential backoff"""
    current_delay = delay
    for attempt in range(1, retries + 1):
        print(f"🔁 Attempt {attempt}/{retries}")
        if func(attempt):
            return True
        if attempt < retries:
            print(f"⏳ Retrying in {current_delay} seconds...")
            time.sleep(current_delay)
            current_delay *= 2
    print("🚨 Maximum retries reached. Exiting.")
    sys.exit(1)


def check_resource_exists(resource_type, resource_name, namespace=None):
    """Check if a Kubernetes resource exists"""
    cmd = ["kubectl", "get", resource_type, resource_name]
    if namespace:
        cmd.extend(["-n", namespace])
    _, _, rc = run_cmd(cmd, capture_output=True)
    return rc == 0


def chart_has_dependencies(chart_path):
    """Return True if Chart.yaml at chart_path declares a top-level dependencies block."""
    chart_yaml = os.path.join(chart_path, "Chart.yaml")
    if not os.path.exists(chart_yaml):
        return False
    with open(chart_yaml, "r", encoding="utf-8") as f:
        return any(line.startswith("dependencies:") for line in f)


def helm_register_chart_dependency_repos(chart_path):
    """Register every dependency repository declared in Chart.yaml.

    `helm dependency build` resolves tarballs by repository URL via
    `helm repo list`. On a fresh host the repo isn't registered and `build`
    fails with `no repository definition for <url>` even when Chart.lock is
    present. Pre-registering each declared repo makes `build` succeed
    quietly without falling back to `helm dependency update`.

    Uses `helm dependency list` to enumerate dependencies so any future
    subchart additions are picked up automatically.
    `helm repo add --force-update` makes the registration idempotent.
    """
    stdout, _, rc = run_cmd(["helm", "dependency", "list", chart_path])
    if rc != 0:
        return
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0] in {"NAME", "WARNING:"}:
            continue
        name, _version, repo = parts[0], parts[1], parts[2]
        if not (repo.startswith("http://") or repo.startswith("https://")):
            continue
        run_cmd(["helm", "repo", "add", "--force-update", name, repo])


def helm_resolve_dependencies(chart_path):
    """Pull subchart dependencies into chart_path/charts/.

    Pre-registers each declared repo (so `build` succeeds on fresh hosts),
    tries `helm dependency build` first (uses Chart.lock for reproducibility),
    and falls back to `helm dependency update` if the lock is missing or stale.
    Returns True on success.
    """
    print(f"📦 Resolving subchart dependencies for '{chart_path}'...")
    helm_register_chart_dependency_repos(chart_path)
    _, stderr, rc = run_cmd(["helm", "dependency", "build", chart_path])
    if rc == 0:
        return True
    print(f"⚠️ helm dependency build failed, retrying with update: {stderr}")
    _, stderr, rc = run_cmd(["helm", "dependency", "update", chart_path])
    if rc != 0:
        print(f"❌ Failed to resolve dependencies:\n{stderr}")
        return False
    return True


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
    _, stderr, rc = run_cmd(["helm", "repo", "update"] + list(repos_to_add.keys()), capture_output=False)
    if rc != 0:
        print(f"❌ Failed to update repos:\n{stderr}")
        sys.exit(1)
    print("✅ Repos added and updated.\n")


def delete_jobs(namespace, skip_buildkit=False):
    """Delete all Jobs in the namespace (Jobs are immutable and block re-apply)"""
    print(f"🗑️ Deleting existing Jobs in namespace '{namespace}'...")
    stdout, _, rc = run_cmd(["kubectl", "get", "jobs", "-n", namespace, "-o", "jsonpath={.items[*].metadata.name}"])
    if rc != 0 or not stdout:
        return
    for job in stdout.split():
        if skip_buildkit and job == "optimizer-buildkit":
            continue
        run_cmd(["kubectl", "delete", "job", job, "-n", namespace, "--ignore-not-found=true"])


def apply_helm_chart_inner(chart_config, namespace, optimizer_version=None, use_force_fallback=False, attempt=1):
    """Apply a single Helm Chart"""
    chart_name = chart_config["name"]
    values_file = chart_config["values_file"]

    # Use chart-specific namespace if defined, otherwise use provided namespace
    target_namespace = chart_config.get("namespace", namespace)

    chart_ref = chart_config["chart_ref"]
    local_path = os.path.join(LOCAL_HELM_DIR, chart_name)
    if os.path.isdir(local_path):
        chart_ref = local_path

    # Local chart paths don't ship dependency tarballs; resolve them so
    # `helm upgrade` can find subcharts under charts/.
    if os.path.isdir(chart_ref) and chart_has_dependencies(chart_ref):
        if not helm_resolve_dependencies(chart_ref):
            return False

    values_path = os.path.join(STAGE_PATH, values_file)

    if attempt > 1:
        delete_jobs(target_namespace, skip_buildkit=True)

    # Use --force-conflicts (Helm 3.13+) or fallback to --force for older versions
    force_flag = "--force" if use_force_fallback else "--force-conflicts"
    cmd = [
        "helm",
        "upgrade",
        "--install",
        force_flag,
        chart_name,
        chart_ref,
        "--namespace",
        target_namespace,
        "--values",
        values_path,
    ]

    # Add version flag if this is the ai-optimizer chart and optimizer_version is "Experimental"
    if chart_name == "ai-optimizer" and optimizer_version == "Experimental":
        cmd.extend(["--version", "0.0.0"])
        print("🔬 Using Experimental version (0.0.0)")
    elif chart_name == "ai-optimizer" and optimizer_version == "Branch":
        print("🔬 Using local Branch chart")
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

    # Fallback: if --force-conflicts is not supported, retry with --force
    if not use_force_fallback and "unknown flag: --force-conflicts" in stderr:
        print("⚠️ Helm version doesn't support --force-conflicts, retrying with --force...")
        return apply_helm_chart_inner(
            chart_config, namespace, optimizer_version, use_force_fallback=True, attempt=attempt
        )

    print(f"❌ Failed to apply Helm chart '{chart_name}':\n{stderr}")
    return False


def apply_helm_chart(chart_config, namespace, optimizer_version=None):
    """Apply a Helm Chart with retry logic"""
    retry(lambda attempt: apply_helm_chart_inner(chart_config, namespace, optimizer_version, attempt=attempt))


def apply_all_helm_charts(namespace, optimizer_version=None):
    """Apply Helm charts in order if their values files exist"""
    charts_to_apply = []
    repos_to_add = {}

    # Discover which charts have values files
    for chart_config in HELM_CHARTS:
        values_path = os.path.join(STAGE_PATH, chart_config["values_file"])
        if os.path.isfile(values_path):
            print(f"✓ Found values file for '{chart_config['name']}': {chart_config['values_file']}")
            charts_to_apply.append(chart_config)

            # Collect remote repos
            if "repo_url" in chart_config:
                repos_to_add[chart_config["repo_name"]] = chart_config["repo_url"]
        else:
            print(f"⊘ Skipping '{chart_config['name']}': values file not found")

    if not charts_to_apply:
        print("\n⚠️ No charts to apply (no matching values files found).\n")
        return

    print()  # Blank line after file detection

    # Add remote Helm repos
    helm_repo_add_if_missing(repos_to_add)

    # Apply charts in order
    print(f"📦 Applying {len(charts_to_apply)} Helm chart(s)...\n")
    for chart_config in charts_to_apply:
        apply_helm_chart(chart_config, namespace, optimizer_version)
        print()

    print("✅ All Helm charts applied successfully.\n")


def apply_manifest_inner(namespace, attempt=1):
    """Apply Kubernetes manifest"""
    manifest_path = os.path.join(STAGE_PATH, "k8s-manifest.yaml")
    if not os.path.isfile(manifest_path):
        print(f"⚠️ Manifest not found: {manifest_path}")
        return False

    if attempt > 1:
        delete_jobs(namespace)

    print("🚀 Applying Kubernetes manifest: k8s-manifest.yaml")
    _, stderr, rc = run_cmd(["kubectl", "apply", "-f", manifest_path], capture_output=False)
    if rc == 0:
        print("✅ Manifest applied.\n")
        return True

    print(f"❌ Failed to apply manifest:\n{stderr}")
    return False


def apply_manifest(namespace):
    """Apply Kubernetes manifest with retry logic"""
    retry(lambda attempt: apply_manifest_inner(namespace, attempt=attempt))


def patch_oracle_operator():
    """Patch Oracle Database Operator deployment and wait for readiness"""
    # Check if namespace exists
    print(f"🔍 Checking if {ORACLE_OPERATOR_NS} namespace exists...")
    if not check_resource_exists("namespace", ORACLE_OPERATOR_NS):
        print(f"⊘ Namespace {ORACLE_OPERATOR_NS} not found. Skipping operator patch.\n")
        return

    # Check if deployment exists
    if not check_resource_exists("deployment", ORACLE_OPERATOR_DEPLOYMENT, ORACLE_OPERATOR_NS):
        print(f"⊘ Deployment {ORACLE_OPERATOR_DEPLOYMENT} not found. Skipping operator patch.\n")
        return

    # Bind manager ClusterRole to the namespace's default ServiceAccount
    if check_resource_exists("clusterrolebinding", ORACLE_OPERATOR_CRB):
        print(f"✓ ClusterRoleBinding {ORACLE_OPERATOR_CRB} already exists.")
    else:
        print(f"🔗 Creating ClusterRoleBinding {ORACLE_OPERATOR_CRB}...")
        crb_cmd = [
            "kubectl",
            "create",
            "clusterrolebinding",
            ORACLE_OPERATOR_CRB,
            f"--clusterrole={ORACLE_OPERATOR_CR}",
            f"--serviceaccount={ORACLE_OPERATOR_NS}:default",
        ]
        _, stderr, rc = run_cmd(crb_cmd, capture_output=False)
        if rc != 0:
            print(f"❌ Failed to create ClusterRoleBinding:\n{stderr}")
            sys.exit(1)
        print("✅ ClusterRoleBinding created.\n")

    # Apply patch
    print("🔧 Patching oracle-database-operator deployment...")
    patch_json = (
        '[{"op": "replace", "path": '
        '"/spec/template/spec/containers/0/securityContext/readOnlyRootFilesystem", '
        '"value": false}]'
    )
    cmd = [
        "kubectl",
        "-n",
        ORACLE_OPERATOR_NS,
        "patch",
        "deployment",
        ORACLE_OPERATOR_DEPLOYMENT,
        "--type",
        "json",
        "-p",
        patch_json,
    ]
    _, stderr, rc = run_cmd(cmd, capture_output=False)
    if rc != 0:
        print(f"❌ Failed to update operator:\n{stderr}")
        sys.exit(1)

    print("✅ Oracle operator updated.\n")

    # Wait for operator to be ready
    print("⏳ Waiting for Oracle Database Operator to be ready...")
    wait_cmd = [
        "kubectl",
        "wait",
        "--for=condition=Available",
        "--timeout=300s",
        "-n",
        ORACLE_OPERATOR_NS,
        f"deployment/{ORACLE_OPERATOR_DEPLOYMENT}",
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
    parser = argparse.ArgumentParser(description="Apply Helm charts and Kubernetes manifests.")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--private_endpoint", help="Kubernetes Private Endpoint")
    parser.add_argument(
        "--optimizer_version",
        choices=["Stable", "Experimental", "Branch"],
        default="Stable",
        help="AI Optimizer version (default: Stable)",
    )
    parser.add_argument(
        "--local_chart_path",
        help="Path to local Helm chart directory (used with Branch mode)",
    )
    args = parser.parse_args()

    if args.local_chart_path:
        for chart in HELM_CHARTS:
            if chart["name"] == "ai-optimizer":
                chart["chart_ref"] = args.local_chart_path
                chart.pop("repo_url", None)
                chart.pop("repo_name", None)

    mod_kubeconfig(args.private_endpoint)
    apply_manifest(args.namespace)
    patch_oracle_operator()
    apply_all_helm_charts(args.namespace, args.optimizer_version)
