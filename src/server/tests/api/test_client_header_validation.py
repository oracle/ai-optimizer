"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Authenticated users cannot select workspace identifiers.
"""

import pytest

_SELECTOR_DETAIL = "The client selector has been removed; the authenticated user selects the workspace"

_HEADER_ENDPOINTS = [
    ("GET", "/v1/embed/MY_VS/files", {}),
    (
        "POST",
        "/v1/testbed/testset_generate",
        {
            "data": {
                "name": "T",
                "ll_model": "openai/test-model",
                "embed_model": "openai/test-embed",
                "questions": "2",
            },
            "files": [("files", ("a.pdf", b"%PDF-", "application/pdf"))],
        },
    ),
    ("GET", "/v1/chat/history", {}),
    ("POST", "/v1/oci/objects/download/my-bucket/DEFAULT", {"json": ["file.txt"]}),
]


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(("method", "path", "request_kwargs"), _HEADER_ENDPOINTS)
@pytest.mark.parametrize("selector", ["", "server", "../../../up"])
async def test_client_header_is_rejected(app_client, auth_headers, method, path, request_kwargs, selector):
    response = await app_client.request(
        method,
        path,
        headers={**auth_headers, "Client": selector},
        **request_kwargs,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": _SELECTOR_DETAIL}


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("selector", ["", "server", "../../../up", "unicode_café"])
async def test_settings_client_query_is_rejected(app_client, auth_headers, selector):
    response = await app_client.get(
        "/v1/settings",
        params={"client": selector},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": _SELECTOR_DETAIL}
