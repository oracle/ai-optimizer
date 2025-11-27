"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import base64
import re
from pathlib import Path
import sys
import argparse
import yaml


def base64_encode_file(file_path: Path) -> str:
    """base64 encode the file contents"""
    return base64.b64encode(file_path.read_bytes()).decode()


def extract_key_files(config_text: str) -> list:
    """Extract the contents of the key_file for the secret"""
    key_file_pattern = re.compile(r"key_file\s*=\s*(.+)")
    return [Path(match.strip()).expanduser() for match in key_file_pattern.findall(config_text)]


def rewrite_key_file_paths(config_text: str) -> str:
    """Write key path for volumeMount"""

    def replacer(match):
        original_path = Path(match.group(1).strip())
        new_path = Path("/app/runtime/.oci") / original_path.name
        return f"key_file={new_path}"

    return re.sub(r"key_file\s*=\s*(.+)", replacer, config_text)


def main():
    """Generate Secret YAML for OCI config file"""

    parser = argparse.ArgumentParser(description="Generate Kubernetes Secret YAML for OCI config")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".oci" / "config",
        help="Path to OCI config file (default: ~/.oci/config)",
    )
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace (default: default)")
    args = parser.parse_args()

    config_path = args.config.expanduser()
    namespace = args.namespace

    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    # Read original config and extract key files
    original_config_text = config_path.read_text(encoding="utf-8")
    key_files = extract_key_files(original_config_text)

    # Check existence of all key files before proceeding
    missing_files = [str(f) for f in key_files if not f.exists()]
    if missing_files:
        print("Error: The following key_file(s) do not exist:")
        for f in missing_files:
            print(f"  - {f}")
        sys.exit(1)

    # Rewrite key_file paths in the config content
    modified_config_text = rewrite_key_file_paths(original_config_text)
    config_b64 = base64.b64encode(modified_config_text.encode()).decode()

    # Read and encode each original key file
    data = {"config": config_b64}
    for key_file in key_files:
        key_name = key_file.name
        data[key_name] = base64_encode_file(key_file)

    # Build Kubernetes Secret YAML
    secret_yaml = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "oci-config-file", "namespace": namespace},
        "type": "Opaque",
        "data": data,
    }

    # Output the YAML
    secret_yaml_str = yaml.dump(secret_yaml, sort_keys=False)
    escaped_yaml = secret_yaml_str.replace("'", "'\"'\"'")
    print(f"echo '{escaped_yaml}' | kubectl apply -f -")


if __name__ == "__main__":
    main()
