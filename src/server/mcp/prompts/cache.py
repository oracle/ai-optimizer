"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared cache for MCP prompt text overrides.
This allows dynamic prompt updates without losing decorator metadata (title, tags).
"""

# Global cache for prompt text overrides
# Key: prompt_name (str), Value: updated prompt text (str)
prompt_text_overrides = {}


def get_override(prompt_name: str) -> str | None:
    """Get the override text for a prompt if it exists"""
    return prompt_text_overrides.get(prompt_name)


def set_override(prompt_name: str, text: str) -> None:
    """Set an override text for a prompt"""
    prompt_text_overrides[prompt_name] = text


def clear_override(prompt_name: str) -> None:
    """Clear the override for a prompt, reverting to default"""
    prompt_text_overrides.pop(prompt_name, None)


def clear_all_overrides() -> None:
    """Clear all prompt overrides"""
    prompt_text_overrides.clear()
