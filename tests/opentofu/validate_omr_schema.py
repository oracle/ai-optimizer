"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore opentofu

import sys
import yaml
from jsonschema import Draft7Validator
from referencing import Registry, Resource


def load_yaml_file(path):
    """Safely Load YAML"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main(schema_file, data_file):
    """Validate OMR Schema"""
    schema = load_yaml_file(schema_file)
    data = load_yaml_file(data_file)

    registry = Registry().with_resource(
        uri="",  # root document
        resource=Resource.from_contents(schema),
    )

    # Create a validator from the root resource
    validator = Draft7Validator(schema, registry=registry)

    # Validate
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)

    if errors:
        for error in errors:
            path = "/".join(map(str, error.absolute_path)) or "<root>"
            print(f"[ERROR] {path}: {error.message}")
        sys.exit(1)
    else:
        print("OMR Schema YAML is valid")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: validate_yaml.py <schema.yaml> <data.yaml>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])