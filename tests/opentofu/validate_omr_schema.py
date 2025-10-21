"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore opentofu

import sys
import yaml
from jsonschema import Draft7Validator
from referencing import Registry, Resource


class DuplicateKeyError(Exception):
    """Exception raised when duplicate keys are found in YAML"""
    pass


class DuplicateKeyChecker(yaml.SafeLoader):
    """Custom YAML loader that detects duplicate keys"""
    pass


def construct_mapping(loader, node):
    """Override construct_mapping to detect duplicate keys"""
    loader.flatten_mapping(node)
    pairs = loader.construct_pairs(node)

    seen_keys = {}
    for key, value in pairs:
        if key in seen_keys:
            # Found a duplicate key
            raise DuplicateKeyError(
                f"Duplicate key '{key}' found at line {node.start_mark.line + 1}"
            )
        seen_keys[key] = value

    return seen_keys


# Register the custom constructor
DuplicateKeyChecker.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_mapping
)


def load_yaml_file(path):
    """Safely Load YAML and check for duplicate keys"""
    with open(path, "r", encoding="utf-8") as f:
        try:
            return yaml.load(f, Loader=DuplicateKeyChecker)
        except DuplicateKeyError as e:
            print(f"[ERROR] {e}")
            sys.exit(1)


def check_duplicate_variables_in_groups(data):
    """Check if any variable appears in multiple variable groups"""
    if "variableGroups" not in data:
        return

    seen_variables = {}
    errors = []

    for idx, group in enumerate(data["variableGroups"]):
        group_title = group.get("title", f"Group {idx}")
        variables = group.get("variables", [])

        for var in variables:
            if var in seen_variables:
                errors.append(
                    f"Variable '{var}' is listed in multiple variable groups: "
                    f"'{seen_variables[var]}' and '{group_title}'"
                )
            else:
                seen_variables[var] = group_title

    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return False

    return True


def main(schema_file, data_file):
    """Validate OMR Schema"""
    schema = load_yaml_file(schema_file)
    data = load_yaml_file(data_file)

    # Check for duplicate variables in variable groups
    has_no_duplicate_vars = check_duplicate_variables_in_groups(data)

    registry = Registry().with_resource(
        uri="",  # root document
        resource=Resource.from_contents(schema),
    )

    # Create a validator from the root resource
    validator = Draft7Validator(schema, registry=registry)

    # Validate
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)

    if errors or not has_no_duplicate_vars:
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