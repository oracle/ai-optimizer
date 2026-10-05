"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for testbed generation utilities.
"""
# spell-checker:disable

import pytest

from server.app.testbed.generation import _extract_json_object, _select_diverse_chunks, jsonl_to_json_content

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
# Generation helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_select_diverse_chunks_chooses_distant_vectors():
    """Farthest-first selection covers semantically different passages."""
    chunks = ["A", "near A", "B"]
    embeddings = [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]]

    selected = _select_diverse_chunks(chunks, embeddings, 2)

    assert selected == [0, 2]


@pytest.mark.unit
def test_select_diverse_chunks_caps_to_available_passages():
    """Question slots can cycle over a passage set smaller than the request."""
    selected = _select_diverse_chunks(["A", "B"], [[1.0, 0.0], [0.0, 1.0]], 5)
    assert selected == [0, 1]


@pytest.mark.unit
def test_extract_json_object_allows_surrounding_text():
    """JSON extraction accepts provider text before and after the object."""
    assert _extract_json_object('Result: {"qa_pairs": []} done') == {"qa_pairs": []}


@pytest.mark.unit
def test_extract_json_object_rejects_invalid_content():
    """Malformed model output has a clear generation error."""
    with pytest.raises(ValueError, match="invalid JSON"):
        _extract_json_object("No JSON here")
