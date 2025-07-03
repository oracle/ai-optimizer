"""
Copyright (c) 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

# spell-checker: disable
"""
import os
from jsonschema import validate
import yaml

meta_schema = os.path.join(os.path.dirname(__file__), "meta_schema.yaml")
schema = os.path.join(os.path.dirname(__file__), "../../opentofu/schema.yaml")

validate(instance=yaml.safe_load(schema), schema=yaml.safe_load(meta_schema))




# import os
# import json
# import yaml
# import jsonschema

# def load_yaml_as_json(file_path):
#     """Load YAML and convert to JSON-compatible dict"""
#     with open(file_path, "r", encoding="utf-8") as f:
#         yaml_data = yaml.safe_load(f)
#         return json.loads(json.dumps(yaml_data))  # ensures compatibility



# validator = Draft202012Validator(meta_schema)
# try:
#     validator.validate(schema_yaml)
#     print("✅ schema.yaml is valid!")
# except Exception as e:
#     print("❌ Validation failed:")
#     print(e)
#     exit(1)
    
# jsonschema.validate(instance=schema, schema=meta_schema)

# def load_yaml(file_path):
#     """Load YAML"""
#     try:
#         with open(file_path, "r", encoding="utf-8") as f:
#             return yaml.safe_load(f)
#     except FileNotFoundError:
#         print(f"❌ Error: The file at {file_path} does not exist.")
#         exit(1)
#     except IOError as e:
#         print(f"❌ Error: Unable to open the file {file_path}. {e}")
#         exit(1)


# schema_yaml = load_yaml(SCHEMA_PATH)
# meta_schema = json.loads(json.dumps(META_SCHEMA))

# # Optional: check meta-schema is valid
# try:
#     jsonschema.Draft202012Validator.check_schema(meta_schema)
# except jsonschema.exceptions.SchemaError as e:
#     print("❌ Meta-schema is invalid:")
#     print(e)
#     exit(1)

# # Perform validation
# try:
#     jsonschema.validate(instance=schema_yaml, schema=meta_schema, cls=jsonschema.Draft202012Validator)
#     print("✅ schema.yaml is valid!")
# except jsonschema.exceptions.SchemaError as e:
#     print("❌ SchemaError during schema validation:")
#     print(e)
#     if e.context:
#         for suberror in e.context:
#             print("Suberror:", suberror.message)
#     exit(1)
# except jsonschema.exceptions.ValidationError as e:
#     print("❌ Validation failed:")
#     print(e.message)
#     print("At path:", list(e.absolute_path))
#     print("Schema path:", list(e.absolute_schema_path))
#     if e.context:
#         for suberror in sorted(e.context, key=lambda se: se.schema_path):
#             print("Suberror:", suberror.message)
#             print("  At path:", list(suberror.absolute_path))
#             print("  Schema path:", list(suberror.absolute_schema_path))
#     exit(1)
