"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import argparse
import base64
import json
import re
import sys
from pathlib import Path

KEY_FILE_PATTERN = re.compile(r"^\s*key_file\s*=\s*(.+?)\s*$", re.MULTILINE)


def base64_encode_file(file_path: Path) -> str:
    """base64 encode the file contents"""
    return base64.b64encode(file_path.read_bytes()).decode()


def extract_key_files(config_text: str) -> list[Path]:
    """Extract the contents of the key_file for the secret"""
    return [Path(match).expanduser() for match in KEY_FILE_PATTERN.findall(config_text)]


def rewrite_key_file_paths(config_text: str) -> str:
    """Write key path for volumeMount"""

    def replacer(match: re.Match[str]) -> str:
        original_path = Path(match.group(1).strip())
        new_path = Path("/app/.oci") / original_path.name
        return f"key_file={new_path}"

    return KEY_FILE_PATTERN.sub(replacer, config_text)


def find_key_name_collisions(key_files: list[Path]) -> list[str]:
    """Return key basenames that cannot be represented safely in one Secret."""
    paths_by_name: dict[str, Path] = {}
    collisions: set[str] = set()

    for key_file in key_files:
        key_name = key_file.name
        if key_name == "config":
            collisions.add(key_name)
            continue

        resolved_path = key_file.resolve()
        existing_path = paths_by_name.get(key_name)
        if existing_path is not None and existing_path != resolved_path:
            collisions.add(key_name)
        else:
            paths_by_name[key_name] = resolved_path

    return sorted(collisions)


def main() -> int:
    """Generate Secret YAML for OCI config file"""

    parser = argparse.ArgumentParser(description="Generate Kubernetes Secret YAML for OCI config")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".oci" / "config",
        help="Path to OCI config file (default: ~/.oci/config)",
    )
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace (default: default)")
    parser.add_argument(
        "--secret-name",
        default="oci-config-file",
        help="Kubernetes Secret name (default: oci-config-file)",
    )
    args = parser.parse_args()

    config_path = args.config.expanduser()
    namespace = args.namespace

    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        return 1

    # Read original config and extract key files
    original_config_text = config_path.read_text(encoding="utf-8")
    key_files = extract_key_files(original_config_text)

    # Check existence of all key files before proceeding
    missing_files = [str(f) for f in key_files if not f.exists()]
    if missing_files:
        print("Error: The following key_file(s) do not exist:", file=sys.stderr)
        for f in missing_files:
            print(f"  - {f}", file=sys.stderr)
        return 1

    key_name_collisions = find_key_name_collisions(key_files)
    if key_name_collisions:
        print("Error: OCI key files cannot share the same filename in one Secret.", file=sys.stderr)
        for key_name in key_name_collisions:
            if key_name == "config":
                print("  - config is a reserved Secret data key", file=sys.stderr)
            else:
                print(f"  - {key_name}", file=sys.stderr)
        return 1

    # Rewrite key_file paths in the config content
    modified_config_text = rewrite_key_file_paths(original_config_text)
    config_b64 = base64.b64encode(modified_config_text.encode()).decode()

    # Read and encode each original key file
    data = {"config": config_b64}
    for key_file in key_files:
        key_name = key_file.name
        data[key_name] = base64_encode_file(key_file)

    # Build Kubernetes Secret YAML
    secret_manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": args.secret_name, "namespace": namespace},
        "type": "Opaque",
        "data": data,
    }

    # JSON is valid input for kubectl apply -f and needs no third-party serializer.
    print(json.dumps(secret_manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
