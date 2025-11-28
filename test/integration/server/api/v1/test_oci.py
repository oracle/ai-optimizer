"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/oci.py

Tests the OCI configuration endpoints through the full API stack.
These endpoints require authentication.

Note: Most OCI operations require valid OCI credentials. Tests without
real OCI credentials will verify endpoint availability and authentication.
"""


class TestOciList:
    """Integration tests for the OCI list endpoint."""

    def test_oci_list_requires_auth(self, client):
        """GET /v1/oci should require authentication."""
        response = client.get("/v1/oci")

        assert response.status_code == 401

    def test_oci_list_rejects_invalid_token(self, client, auth_headers):
        """GET /v1/oci should reject invalid tokens."""
        response = client.get("/v1/oci", headers=auth_headers["invalid_auth"])

        assert response.status_code == 401

    def test_oci_list_accepts_valid_token(self, client, auth_headers):
        """GET /v1/oci should accept valid tokens."""
        response = client.get("/v1/oci", headers=auth_headers["valid_auth"])

        # May return 200 (with configs) or 404 (no configs)
        assert response.status_code in [200, 404]

    def test_oci_list_returns_list_or_404(self, client, auth_headers):
        """GET /v1/oci should return a list of OCI configs or 404 if none."""
        response = client.get("/v1/oci", headers=auth_headers["valid_auth"])

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
        else:
            assert response.status_code == 404


class TestOciGet:
    """Integration tests for the single OCI profile get endpoint."""

    def test_oci_get_requires_auth(self, client):
        """GET /v1/oci/{auth_profile} should require authentication."""
        response = client.get("/v1/oci/DEFAULT")

        assert response.status_code == 401

    def test_oci_get_returns_404_for_unknown(self, client, auth_headers):
        """GET /v1/oci/{auth_profile} should return 404 for unknown profile."""
        response = client.get(
            "/v1/oci/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 404


class TestOciRegions:
    """Integration tests for the OCI regions endpoint."""

    def test_oci_regions_requires_auth(self, client):
        """GET /v1/oci/regions/{auth_profile} should require authentication."""
        response = client.get("/v1/oci/regions/DEFAULT")

        assert response.status_code == 401

    def test_oci_regions_returns_404_for_unknown_profile(self, client, auth_headers):
        """GET /v1/oci/regions/{auth_profile} should return 404 for unknown profile."""
        response = client.get(
            "/v1/oci/regions/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 404


class TestOciGenai:
    """Integration tests for the OCI GenAI models endpoint."""

    def test_oci_genai_requires_auth(self, client):
        """GET /v1/oci/genai/{auth_profile} should require authentication."""
        response = client.get("/v1/oci/genai/DEFAULT")

        assert response.status_code == 401

    def test_oci_genai_returns_404_for_unknown_profile(self, client, auth_headers):
        """GET /v1/oci/genai/{auth_profile} should return 404 for unknown profile."""
        response = client.get(
            "/v1/oci/genai/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 404


class TestOciCompartments:
    """Integration tests for the OCI compartments endpoint."""

    def test_oci_compartments_requires_auth(self, client):
        """GET /v1/oci/compartments/{auth_profile} should require authentication."""
        response = client.get("/v1/oci/compartments/DEFAULT")

        assert response.status_code == 401

    def test_oci_compartments_returns_404_for_unknown_profile(self, client, auth_headers):
        """GET /v1/oci/compartments/{auth_profile} should return 404 for unknown profile."""
        response = client.get(
            "/v1/oci/compartments/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 404


class TestOciBuckets:
    """Integration tests for the OCI buckets endpoint."""

    def test_oci_buckets_requires_auth(self, client):
        """GET /v1/oci/buckets/{compartment_ocid}/{auth_profile} should require authentication."""
        response = client.get("/v1/oci/buckets/ocid1.compartment.oc1..test/DEFAULT")

        assert response.status_code == 401

    def test_oci_buckets_returns_404_for_unknown_profile(self, client, auth_headers):
        """GET /v1/oci/buckets/{compartment_ocid}/{auth_profile} should return 404 for unknown profile."""
        response = client.get(
            "/v1/oci/buckets/ocid1.compartment.oc1..test/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 404


class TestOciObjects:
    """Integration tests for the OCI bucket objects endpoint."""

    def test_oci_objects_requires_auth(self, client):
        """GET /v1/oci/objects/{bucket_name}/{auth_profile} should require authentication."""
        response = client.get("/v1/oci/objects/test-bucket/DEFAULT")

        assert response.status_code == 401

    def test_oci_objects_returns_404_for_unknown_profile(self, client, auth_headers):
        """GET /v1/oci/objects/{bucket_name}/{auth_profile} should return 404 for unknown profile."""
        response = client.get(
            "/v1/oci/objects/test-bucket/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 404


class TestOciUpdate:
    """Integration tests for the OCI profile update endpoint."""

    def test_oci_update_requires_auth(self, client):
        """PATCH /v1/oci/{auth_profile} should require authentication."""
        response = client.patch(
            "/v1/oci/DEFAULT",
            json={"auth_profile": "DEFAULT", "genai_region": "us-ashburn-1"},
        )

        assert response.status_code == 401

    def test_oci_update_returns_404_for_unknown_profile(self, client, auth_headers):
        """PATCH /v1/oci/{auth_profile} should return 404 for unknown profile."""
        response = client.patch(
            "/v1/oci/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
            json={"auth_profile": "NONEXISTENT_PROFILE", "genai_region": "us-ashburn-1"},
        )

        assert response.status_code == 404


class TestOciDownloadObjects:
    """Integration tests for the OCI download objects endpoint."""

    def test_oci_download_requires_auth(self, client):
        """POST /v1/oci/objects/download/{bucket_name}/{auth_profile} should require authentication."""
        response = client.post(
            "/v1/oci/objects/download/test-bucket/DEFAULT",
            json=["file1.txt"],
        )

        assert response.status_code == 401

    def test_oci_download_returns_404_for_unknown_profile(self, client, auth_headers):
        """POST /v1/oci/objects/download/{bucket_name}/{auth_profile} should return 404 for unknown profile."""
        response = client.post(
            "/v1/oci/objects/download/test-bucket/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
            json=["file1.txt"],
        )

        assert response.status_code == 404


class TestOciCreateGenaiModels:
    """Integration tests for the OCI create GenAI models endpoint."""

    def test_oci_create_genai_requires_auth(self, client):
        """POST /v1/oci/genai/{auth_profile} should require authentication."""
        response = client.post("/v1/oci/genai/DEFAULT")

        assert response.status_code == 401

    def test_oci_create_genai_returns_404_for_unknown_profile(self, client, auth_headers):
        """POST /v1/oci/genai/{auth_profile} should return 404 for unknown profile."""
        response = client.post(
            "/v1/oci/genai/NONEXISTENT_PROFILE",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 404
