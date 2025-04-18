"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

from typing import Any, Dict
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from conftest import TEST_HEADERS, TEST_BAD_HEADERS


#####################################################
# Mocks
#####################################################
@pytest.fixture(name="mock_get_compartments")
def _mock_get_compartments():
    """Mock server_oci.get_compartments"""
    with patch(
        "server.utils.oci.get_compartments",
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
        "server.utils.oci.get_buckets",
        return_value=["bucket1", "bucket2", "bucket3"],
    ) as mock:
        yield mock


@pytest.fixture(name="mock_get_bucket_objects")
def _mock_get_bucket_objects():
    """Mock server_oci.get_bucket_objects"""
    with patch(
        "server.utils.oci.get_bucket_objects",
        return_value=["object1.pdf", "object2.md", "object3.txt"],
    ) as mock:
        yield mock


@pytest.fixture(name="mock_get_object")
def _mock_get_object(mock_init_client):
    """Mock get_object to return a fake file path"""
    assert mock_init_client is not None
    with patch("server.utils.oci.get_object") as mock:

        def side_effect(temp_directory, object_name, bucket_name, oci_config):
            del bucket_name, oci_config
            fake_file = temp_directory / object_name
            fake_file.touch()  # Create an empty file to simulate download

        mock.side_effect = side_effect
        yield mock


#####################################################
# Test AuthN required and Valid
#####################################################
class TestNoAuthEndpoints:
    """Test endpoints without AuthN"""

    test_cases = [
        pytest.param(
            {"endpoint": "/v1/oci", "method": "get"},
            id="oci_list",
        ),
        pytest.param(
            {"endpoint": "/v1/oci/DEFAULT", "method": "get"},
            id="oci_get",
        ),
        pytest.param(
            {"endpoint": "/v1/oci/compartments/DEFAULT", "method": "get"},
            id="oci_list_compartments",
        ),
        pytest.param(
            {"endpoint": "/v1/oci/buckets/compartment/DEFAULT", "method": "get"},
            id="oci_list_buckets",
        ),
        pytest.param(
            {"endpoint": "/v1/oci/objects/bucket/DEFAULT", "method": "get"},
            id="oci_list_bucket_objects",
        ),
        pytest.param(
            {"endpoint": "/v1/oci/DEFAULT", "method": "patch"},
            id="oci_profile_update",
        ),
        pytest.param(
            {"endpoint": "/v1/oci/objects/download/bucket/DEFAULT", "method": "post"},
            id="oci_download_objects",
        ),
    ]

    @pytest.mark.parametrize("test_case", test_cases)
    def test_no_auth(self, client: TestClient, test_case: Dict[str, Any]) -> None:
        """Testing for required AuthN"""
        response = getattr(client, test_case["method"])(test_case["endpoint"])
        assert response.status_code == 403
        response = getattr(client, test_case["method"])(test_case["endpoint"], headers=TEST_BAD_HEADERS)
        assert response.status_code == 401


#############################################################################
# Test AuthN - No OS Env
#############################################################################
class TestEndpoints:
    """Test endpoints with AuthN"""

    DEFAULT_CONFIG = {
        "auth_profile": "DEFAULT",
        "namespace": None,
        "user": None,
        "security_token_file": None,
        "tenancy": None,
        "region": None,
        "fingerprint": None,
        "key_file": None,
        "compartment_id": "",
        "service_endpoint": "",
        "log_requests": False,
        "additional_user_agent": "",
        "pass_phrase": None,
        "authentication": "api_key",
    }

    def test_oci_list(self, client: TestClient) -> None:
        """List OCI Configuration"""
        response = client.get("/v1/oci", headers=TEST_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data == [self.DEFAULT_CONFIG]

    def test_oci_get(self, client: TestClient):
        """List OCI Configuration"""
        response = client.get("/v1/oci/DEFAULT", headers=TEST_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data == self.DEFAULT_CONFIG
        response = client.get("/v1/oci/TEST", headers=TEST_HEADERS)
        assert response.status_code == 404
        assert response.json() == {"detail": "OCI: Profile TEST not found."}

    def test_oci_list_compartments(self, client: TestClient, mock_get_compartments):
        """List OCI Compartments"""
        response = client.get("/v1/oci/compartments/DEFAULT", headers=TEST_HEADERS)
        assert response.status_code == 200
        assert response.json() == mock_get_compartments.return_value
        response = client.get("/v1/oci/compartments/TEST", headers=TEST_HEADERS)
        assert response.status_code == 404
        assert response.json() == {"detail": "OCI: Profile TEST not found."}

    def test_oci_list_buckets(self, client: TestClient, mock_get_buckets):
        """List OCI Buckets"""
        response = client.get("/v1/oci/buckets/ocid1.compartment.oc1..aaaaaaaa/DEFAULT", headers=TEST_HEADERS)
        assert response.status_code == 200
        assert response.json() == mock_get_buckets.return_value
        response = client.get("/v1/oci/buckets/ocid1.compartment.oc1..aaaaaaaa/TEST", headers=TEST_HEADERS)
        assert response.status_code == 404
        assert response.json() == {"detail": "OCI: Profile TEST not found."}

    def test_oci_list_bucket_objects(self, client: TestClient, mock_get_bucket_objects):
        """List OCI Bucket Objects"""
        response = client.get("/v1/oci/objects/bucket1/DEFAULT", headers=TEST_HEADERS)
        assert response.status_code == 200
        assert response.json() == mock_get_bucket_objects.return_value
        response = client.get("/v1/oci/objects/bucket1/TEST", headers=TEST_HEADERS)
        assert response.status_code == 404
        assert response.json() == {"detail": "OCI: Profile TEST not found."}

    test_cases = [
        pytest.param(
            {
                "profile": "DEFAULT",
                "payload": "",
                "status_code": 422,
            },
            id="empty_payload",
        ),
        pytest.param(
            {
                "profile": "DEFAULT",
                "payload": {},
                "status_code": 400,
            },
            id="invalid_payload",
        ),
        pytest.param(
            {
                "profile": "DEFAULT",
                "payload": {
                    "tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
                    "user": "ocid1.user.oc1..aaaaaaaa",
                    "region": "us-ashburn-1",
                    "fingerprint": "e8:65:45:4a:85:4b:6c:51:63:b8:84:64:ef:36:16:7b",
                    "key_file": "/dev/null",
                },
                "status_code": 200,
            },
            id="valid_default_profile",
        ),
        pytest.param(
            {
                "profile": "TEST",
                "payload": {
                    "tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
                    "user": "ocid1.user.oc1..aaaaaaaa",
                    "region": "us-ashburn-1",
                    "fingerprint": "e8:65:45:4a:85:4b:6c",
                    "key_file": "/tmp/key.pem",
                },
                "status_code": 404,
            },
            id="valid_test_profile",
        ),
    ]

    @pytest.mark.parametrize("test_case", test_cases)
    def test_oci_profile_update(self, client: TestClient, test_case: Dict[str, Any], mock_get_namespace):
        """Update Profile"""
        response = client.patch(f"/v1/oci/{test_case['profile']}", headers=TEST_HEADERS, json=test_case["payload"])
        assert response.status_code == test_case["status_code"]
        if test_case["status_code"] == 200:
            data = response.json()
            assert data["namespace"] == mock_get_namespace.return_value

    def test_oci_download_objects(
        self,
        client: TestClient,
        mock_get_compartments,
        mock_get_buckets,
        mock_get_bucket_objects,
        mock_get_object,
        mock_get_temp_directory,
    ):
        """OCI Object Download"""
        # Get Compartments
        response = client.get("/v1/oci/compartments/DEFAULT", headers=TEST_HEADERS)
        assert response.status_code == 200
        assert response.json() == mock_get_compartments.return_value
        compartment = response.json()[next(iter(response.json()))]

        # Get Buckets
        response = client.get(f"/v1/oci/buckets/{compartment}/DEFAULT", headers=TEST_HEADERS)
        assert response.status_code == 200
        assert response.json() == mock_get_buckets.return_value
        bucket = response.json()[0]

        # Get Bucket Objects
        response = client.get(f"/v1/oci/objects/{bucket}/DEFAULT", headers=TEST_HEADERS)
        assert response.status_code == 200
        assert response.json() == mock_get_bucket_objects.return_value
        payload = response.json()

        # Download
        assert mock_get_object is not None
        response = client.post(f"/v1/oci/objects/download/{bucket}/DEFAULT", headers=TEST_HEADERS, json=payload)
        assert response.status_code == 200
        assert set(response.json()) == set(mock_get_bucket_objects.return_value)

        # Verify the mock was called (accessing the mock object)
        assert mock_get_temp_directory.called
