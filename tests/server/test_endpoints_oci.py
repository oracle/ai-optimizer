"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock
import pytest


#############################################################################
# Test AuthN required and Valid
#############################################################################
class TestInvalidAuthEndpoints:
    """Test endpoints without Headers and Invalid AuthN"""

    @pytest.mark.parametrize(
        "auth_type, status_code",
        [
            pytest.param("no_auth", 403, id="no_auth"),
            pytest.param("invalid_auth", 401, id="invalid_auth"),
        ],
    )
    @pytest.mark.parametrize(
        "endpoint, api_method",
        [
            pytest.param("/v1/oci", "get", id="oci_list"),
            pytest.param("/v1/oci/DEFAULT", "get", id="oci_get"),
            pytest.param("/v1/oci/compartments/DEFAULT", "get", id="oci_list_compartments"),
            pytest.param("/v1/oci/buckets/ocid/DEFAULT", "get", id="oci_list_buckets"),
            pytest.param("/v1/oci/objects/bucket/DEFAULT", "get", id="oci_list_bucket_objects"),
            pytest.param("/v1/oci/DEFAULT", "patch", id="oci_profile_update"),
            pytest.param("/v1/oci/objects/download/bucket/DEFAULT", "post", id="oci_download_objects"),
        ],
    )
    def test_endpoints(self, client, auth_headers, endpoint, api_method, auth_type, status_code):
        """Test endpoints require valide authentication"""
        response = getattr(client, api_method)(endpoint, headers=auth_headers[auth_type])
        assert response.status_code == status_code


############################################################################
# Mocks as no OCI Access
############################################################################
def mock_client_response(client, method, status_code=200, json_data=None):
    """Context manager to mock client responses"""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    if json_data is not None:
        mock_response.json.return_value = json_data
    return patch.object(client, method, return_value=mock_response)


@pytest.fixture(name="mock_init_client")
def _mock_init_client():
    """Mock init_client to return a fake OCI client"""
    mock_client = MagicMock()
    mock_client.get_namespace.return_value.data = "test_namespace"
    mock_client.get_object.return_value.data.raw.stream.return_value = [b"fake-data"]

    with patch("server.api.util.oci.init_client", return_value=mock_client):
        yield mock_client


@pytest.fixture(name="mock_get_compartments")
def _mock_get_compartments():
    """Mock get_compartments"""
    with patch(
        "server.api.util.oci.get_compartments",
        return_value={
            "compartment1": "ocid1.compartment.oc1..aaaaaaaagq33tv7wzyrjar6m5jbplejbdwnbjqfqvmocvjzsamuaqnkkoubq",
            "compartment1 / test": "ocid1.compartment.oc1..aaaaaaaaut53mlkpxo6vpv7z5qlsmbcc3qpdjvjzylzldtb6g3jia",
            "compartment2": "ocid1.compartment.oc1..aaaaaaaalbgt4om6izlawie7txut5aciue66htz7dpjzl72fbdw2ezp2uywa",
        },
    ) as mock:
        yield mock


@pytest.fixture(name="mock_get_buckets")
def _mock_get_buckets():
    """Mock server_oci.get_buckets"""
    with patch(
        "server.api.util.oci.get_buckets",
        return_value=["bucket1", "bucket2", "bucket3"],
    ) as mock:
        yield mock


@pytest.fixture(name="mock_get_bucket_objects")
def _mock_get_bucket_objects():
    """Mock server_oci.get_bucket_objects"""
    with patch(
        "server.api.util.oci.get_bucket_objects",
        return_value=["object1.pdf", "object2.md", "object3.txt"],
    ) as mock:
        yield mock


@pytest.fixture(name="mock_get_namespace")
def _mock_get_namespace():
    """Mock server_oci.get_namespace"""
    with patch("server.api.util.oci.get_namespace", return_value="test_namespace") as mock:
        yield mock


@pytest.fixture(name="mock_get_object")
def _mock_get_object():
    """Mock get_object to return a fake file path"""
    with patch("server.api.util.oci.get_object") as mock:

        def side_effect(temp_directory, object_name):
            fake_file = temp_directory / object_name
            fake_file.touch()  # Create an empty file to simulate download
            return str(fake_file)  # Return the path as string to match the actual function

        mock.side_effect = side_effect
        yield mock

############################################################################
# Endpoints Test
############################################################################
class TestEndpoints:
    """Test Endpoints"""

    def test_oci_list(self, client, auth_headers):
        """List OCI Configuration"""
        response = client.get("/v1/oci", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        # The endpoint returns a list of OracleCloudSettings
        assert isinstance(response.json(), list)
        # Each item in the list should be a valid OracleCloudSettings object
        for item in response.json():
            assert "auth_profile" in item
            assert item["auth_profile"] in ["DEFAULT"]  # At minimum, DEFAULT profile should exist

    def test_oci_get(self, client, auth_headers):
        """List OCI Configuration"""
        response = client.get("/v1/oci/DEFAULT", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        data = response.json()
        assert data["auth_profile"] == "DEFAULT"
        response = client.get("/v1/oci/TEST", headers=auth_headers["valid_auth"])
        assert response.status_code == 404
        assert response.json() == {"detail": "OCI: profile 'TEST' not found"}

    def test_oci_list_compartments(self, client, auth_headers, mock_get_compartments):
        """List OCI Compartments"""
        with mock_client_response(client, "get", 200, mock_get_compartments.return_value) as mock_get:
            # Test DEFAULT profile
            response = client.get("/v1/oci/compartments/DEFAULT", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            assert response.json() == mock_get_compartments.return_value

            # Test TEST profile
            mock_get.return_value.status_code = 404
            mock_get.return_value.json.return_value = {"detail": "OCI: profile 'TEST' not found"}
            response = client.get("/v1/oci/compartments/TEST", headers=auth_headers["valid_auth"])
            assert response.status_code == 404
            assert response.json() == {"detail": "OCI: profile 'TEST' not found"}

    def test_oci_list_buckets(self, client, auth_headers, mock_get_buckets):
        """List OCI Buckets"""
        with mock_client_response(client, "get", 200, mock_get_buckets.return_value) as mock_get:
            response = client.get(
                "/v1/oci/buckets/ocid1.compartment.oc1..aaaaaaaa/DEFAULT", headers=auth_headers["valid_auth"]
            )
            assert response.status_code == 200
            assert response.json() == mock_get_buckets.return_value

            # Test TEST profile
            mock_get.return_value.status_code = 404
            mock_get.return_value.json.return_value = {"detail": "OCI: profile 'TEST' not found"}
            response = client.get(
                "/v1/oci/buckets/ocid1.compartment.oc1..aaaaaaaa/TEST", headers=auth_headers["valid_auth"]
            )
            assert response.status_code == 404
            assert response.json() == {"detail": "OCI: profile 'TEST' not found"}

    def test_oci_list_bucket_objects(self, client, auth_headers, mock_get_bucket_objects):
        """List OCI Bucket Objects"""
        with mock_client_response(client, "get", 200, mock_get_bucket_objects.return_value) as mock_get:
            response = client.get("/v1/oci/objects/bucket1/DEFAULT", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            assert response.json() == mock_get_bucket_objects.return_value

            # Test TEST profile
            mock_get.return_value.status_code = 404
            mock_get.return_value.json.return_value = {"detail": "OCI: profile 'TEST' not found"}
            response = client.get("/v1/oci/objects/bucket1/TEST", headers=auth_headers["valid_auth"])
            assert response.status_code == 404
            assert response.json() == {"detail": "OCI: profile 'TEST' not found"}

    test_cases = [
        pytest.param("DEFAULT", "", 422, id="empty_payload"),
        pytest.param("DEFAULT", {}, 400, id="invalid_payload"),
        pytest.param(
            "DEFAULT",
            {
                "tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
                "user": "ocid1.user.oc1..aaaaaaaa",
                "region": "us-ashburn-1",
                "fingerprint": "e8:65:45:4a:85:4b:6c:51:63:b8:84:64:ef:36:16:7b",
                "key_file": "/dev/null",
            },
            200,
            id="valid_default_profile",
        ),
        pytest.param(
            "TEST",
            {
                "tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
                "user": "ocid1.user.oc1..aaaaaaaa",
                "region": "us-ashburn-1",
                "fingerprint": "e8:65:45:4a:85:4b:6c",
                "key_file": "/tmp/key.pem",
            },
            404,
            id="valid_test_profile",
        ),
    ]

    @pytest.mark.parametrize("profile, payload, status_code", test_cases)
    def test_oci_profile_update(self, client, auth_headers, profile, payload, status_code, mock_get_namespace):
        """Update Profile"""
        json_data = {"namespace": mock_get_namespace.return_value} if status_code == 200 else None
        with mock_client_response(client, "patch", status_code, json_data):
            response = client.patch(f"/v1/oci/{profile}", headers=auth_headers["valid_auth"], json=payload)
            assert response.status_code == status_code
            if status_code == 200:
                data = response.json()
                assert data["namespace"] == mock_get_namespace.return_value

    def test_oci_download_objects(
        self, client, auth_headers, mock_get_compartments, mock_get_buckets, mock_get_bucket_objects, mock_get_object
    ):
        """OCI Object Download"""
        # Get Compartments
        with mock_client_response(client, "get", 200, mock_get_compartments.return_value):
            response = client.get("/v1/oci/compartments/DEFAULT", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            assert response.json() == mock_get_compartments.return_value
            compartment = response.json()[next(iter(response.json()))]

        # Get Buckets
        with mock_client_response(client, "get", 200, mock_get_buckets.return_value):
            response = client.get(f"/v1/oci/buckets/{compartment}/DEFAULT", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            assert response.json() == mock_get_buckets.return_value
            bucket = response.json()[0]

        # Get Bucket Objects
        with mock_client_response(client, "get", 200, mock_get_bucket_objects.return_value):
            response = client.get(f"/v1/oci/objects/{bucket}/DEFAULT", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            assert response.json() == mock_get_bucket_objects.return_value
            payload = response.json()

        # Download
        assert mock_get_object is not None
        with mock_client_response(client, "post", 200, mock_get_bucket_objects.return_value):
            response = client.post(
                f"/v1/oci/objects/download/{bucket}/DEFAULT", headers=auth_headers["valid_auth"], json=payload
            )
            assert response.status_code == 200
            assert set(response.json()) == set(mock_get_bucket_objects.return_value)
