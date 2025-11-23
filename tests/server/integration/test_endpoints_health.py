"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

import pytest


@pytest.mark.parametrize(
    "endpoint, status_msg",
    [
        pytest.param("/v1/liveness", {"status": "alive"}, id="liveness"),
        pytest.param("/v1/readiness", {"status": "ready"}, id="readiness"),
    ],
)
@pytest.mark.parametrize(
    "auth_type",
    [
        pytest.param("no_auth", id="no_auth"),
        pytest.param("invalid_auth", id="invalid_auth"),
        pytest.param("valid_auth", id="valid_auth"),
    ],
)
def test_health_endpoints(client, auth_headers, endpoint, status_msg, auth_type):
    """Test that health check endpoints work with or without authentication."""
    response = client.get(endpoint, headers=auth_headers[auth_type])
    assert response.status_code == 200  # Health endpoints should always return 200
    assert response.json() == status_msg
