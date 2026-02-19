"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/oci.py

Tests the OCI configuration endpoints through the full API stack.
These endpoints require authentication.

Note: Most OCI operations require valid OCI credentials. Tests without
real OCI credentials will verify endpoint availability and authentication.
"""

from unittest.mock import patch, MagicMock
import pytest


############################################################################
# Mocks for OCI endpoints (no real OCI access)
############################################################################
@pytest.fixture(name="mock_oci_compartments")
def _mock_oci_compartments():
    """Mock get_compartments to return test data"""
    with patch(
        "server.api.utils.oci.get_compartments",
        return_value={
            "compartment1": "ocid1.compartment.oc1..aaaaaaaagq33tv7wzyrjar6m5jbplejbdwnbjqfqvmocvjzsamuaqnkkoubq",
            "compartment1 / test": "ocid1.compartment.oc1..aaaaaaaaut53mlkpxo6vpv7z5qlsmbcc3qpdjvjzylzldtb6g3jia",
            "compartment2": "ocid1.compartment.oc1..aaaaaaaalbgt4om6izlawie7txut5aciue66htz7dpjzl72fbdw2ezp2uywa",
        },
    ) as mock:
        yield mock


@pytest.fixture(name="mock_oci_buckets")
def _mock_oci_buckets():
    """Mock get_buckets to return test data"""
    with patch(
        "server.api.utils.oci.get_buckets",
        return_value=["bucket1", "bucket2", "bucket3"],
    ) as mock:
        yield mock


@pytest.fixture(name="mock_oci_bucket_objects")
def _mock_oci_bucket_objects():
    """Mock get_bucket_objects to return test data"""
    with patch(
        "server.api.utils.oci.get_bucket_objects",
        return_value=["object1.pdf", "object2.md", "object3.txt"],
    ) as mock:
        yield mock


@pytest.fixture(name="mock_oci_namespace")
def _mock_oci_namespace():
    """Mock get_namespace to return test data"""
    with patch("server.api.utils.oci.get_namespace", return_value="test_namespace") as mock:
        yield mock


@pytest.fixture(name="mock_oci_get_object")
def _mock_oci_get_object():
    """Mock get_object to return a fake file path"""
    with patch("server.api.utils.oci.get_object") as mock:

        def side_effect(temp_directory, object_name, bucket_name, config):
            # pylint: disable=unused-argument
            fake_file = temp_directory / object_name
            fake_file.touch()
            return str(fake_file)

        mock.side_effect = side_effect
        yield mock


@pytest.fixture(name="mock_oci_init_client")
def _mock_oci_init_client():
    """Mock init_client to return a fake OCI client"""
    mock_client = MagicMock()
    mock_client.get_namespace.return_value.data = "test_namespace"
    mock_client.get_object.return_value.data.raw.stream.return_value = [b"fake-data"]

    with patch("server.api.utils.oci.init_client", return_value=mock_client):
        yield mock_client


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


class TestOciListWithValidation:
    """Integration tests with response validation for OCI list endpoint."""

    def test_oci_list_returns_profiles_with_auth_profile(self, client, auth_headers):
        """GET /v1/oci should return list with auth_profile field."""
        response = client.get("/v1/oci", headers=auth_headers["valid_auth"])

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
            for item in data:
                assert "auth_profile" in item

    def test_oci_get_returns_profile_data(self, client, auth_headers):
        """GET /v1/oci/{profile} should return profile data when exists."""
        # First check if DEFAULT profile exists
        list_response = client.get("/v1/oci", headers=auth_headers["valid_auth"])

        if list_response.status_code == 200:
            profiles = list_response.json()
            if any(p.get("auth_profile") == "DEFAULT" for p in profiles):
                response = client.get("/v1/oci/DEFAULT", headers=auth_headers["valid_auth"])
                assert response.status_code == 200
                data = response.json()
                assert data["auth_profile"] == "DEFAULT"


class TestOciUpdateValidation:
    """Integration tests for OCI profile update validation."""

    def test_oci_update_empty_payload_returns_422(self, client, auth_headers):
        """PATCH /v1/oci/{profile} with empty payload should return 422."""
        response = client.patch("/v1/oci/DEFAULT", headers=auth_headers["valid_auth"], json="")
        assert response.status_code == 422

    def test_oci_update_invalid_payload_returns_400_or_404(self, client, auth_headers):
        """PATCH /v1/oci/{profile} with invalid payload should return 400 or 404."""
        response = client.patch("/v1/oci/DEFAULT", headers=auth_headers["valid_auth"], json={})
        # 400 if profile exists but payload invalid, 404 if profile doesn't exist
        assert response.status_code in [400, 404]


class TestOciWithMocks:
    """Integration tests using mocks for OCI operations requiring credentials."""

    def test_oci_compartments_with_mock(self, client, auth_headers, mock_oci_compartments):
        """Test compartments endpoint with mocked OCI data."""
        # This test will get 404 if DEFAULT profile doesn't exist
        # The mock is for the underlying OCI call, not the profile lookup
        response = client.get("/v1/oci/compartments/DEFAULT", headers=auth_headers["valid_auth"])

        # Either returns mocked data (200) or profile not found (404)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            assert response.json() == mock_oci_compartments.return_value

    def test_oci_buckets_with_mock(self, client, auth_headers, mock_oci_buckets):
        """Test buckets endpoint with mocked OCI data."""
        response = client.get(
            "/v1/oci/buckets/ocid1.compartment.oc1..aaaaaaaa/DEFAULT",
            headers=auth_headers["valid_auth"],
        )

        # Either returns mocked data (200) or profile not found (404)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            assert response.json() == mock_oci_buckets.return_value

    def test_oci_bucket_objects_with_mock(self, client, auth_headers, mock_oci_bucket_objects):
        """Test bucket objects endpoint with mocked OCI data."""
        response = client.get("/v1/oci/objects/bucket1/DEFAULT", headers=auth_headers["valid_auth"])

        # Either returns mocked data (200) or profile not found (404)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            assert response.json() == mock_oci_bucket_objects.return_value

    def test_oci_download_objects_with_mock(
        self, client, auth_headers, mock_oci_bucket_objects, mock_oci_get_object
    ):
        """Test download objects endpoint with mocked OCI data."""
        # pylint: disable=unused-argument
        payload = ["object1.pdf", "object2.md"]
        response = client.post(
            "/v1/oci/objects/download/bucket1/DEFAULT",
            headers=auth_headers["valid_auth"],
            json=payload,
        )

        # Either returns downloaded files (200) or profile not found (404)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            assert isinstance(response.json(), list)
