"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for testbed generation utilities.
"""
# spell-checker:disable

import pytest

from server.app.testbed.generation import get_giskard_config, jsonl_to_json_content

# ---------------------------------------------------------------------------
# jsonl_to_json_content
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_jsonl_single_json_object():
    """Single JSON object passes through."""
    result = jsonl_to_json_content('{"question": "What?", "answer": "Yes."}')
    assert '"question"' in result
    assert '"answer"' in result


@pytest.mark.unit
def test_jsonl_json_array():
    """JSON array passes through."""
    result = jsonl_to_json_content('[{"q": "a"}, {"q": "b"}]')
    assert result.startswith("[")


@pytest.mark.unit
def test_jsonl_multi_line():
    """JSONL (newline-delimited) is converted to a JSON array."""
    content = '{"q": "a"}\n{"q": "b"}'
    result = jsonl_to_json_content(content)
    assert result.startswith("[")


@pytest.mark.unit
def test_jsonl_single_line_jsonl():
    """Single-line JSONL returns the object directly (not wrapped in array)."""
    result = jsonl_to_json_content('{"q": "a"}')
    assert result.startswith("{")


@pytest.mark.unit
def test_jsonl_bytes_input():
    """Bytes input is decoded to UTF-8 before parsing."""
    result = jsonl_to_json_content(b'{"q": "a"}')
    assert '"q"' in result


@pytest.mark.unit
def test_jsonl_invalid_content():
    """Invalid content raises ValueError."""
    with pytest.raises(ValueError, match="Invalid JSONL"):
        jsonl_to_json_content("not json at all\nalso not json")


# ---------------------------------------------------------------------------
# get_giskard_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_giskard_config_ll_model():
    """LL model config renames 'model' to 'llm_model' and strips params."""
    config = {
        "model": "openai/gpt-5-mini",
        "temperature": 0.5,
        "max_tokens": 4096,
        "api_base": "https://api.openai.com",
        "api_key": "sk-test",
    }
    result = get_giskard_config(config, "ll")
    assert "llm_model" in result
    assert result["llm_model"] == "openai/gpt-5-mini"
    assert "model" not in result
    assert "temperature" not in result
    assert "max_tokens" not in result
    assert result["api_key"] == "sk-test"


@pytest.mark.unit
def test_giskard_config_embed_model():
    """Embed model config preserves 'model' key and max_chunk_size."""
    config = {
        "model": "openai/text-embedding-3-small",
        "temperature": 0.5,
        "max_tokens": 8192,
        "max_chunk_size": 512,
    }
    result = get_giskard_config(config, "embed")
    assert result["model"] == "openai/text-embedding-3-small"
    assert result["max_chunk_size"] == 512
    assert "temperature" not in result
    assert "max_tokens" not in result


@pytest.mark.unit
def test_giskard_config_does_not_mutate_original():
    """get_giskard_config does not mutate the input dict."""
    config = {"model": "openai/gpt-5-mini", "temperature": 0.5}
    get_giskard_config(config, "ll")
    assert "model" in config
    assert "temperature" in config
