"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from conftest import TEST_CONFIG
from langchain_core.embeddings import Embeddings
from common.functions import get_vs_table

# Common test constants
DEFAULT_TEST_CONTENT = (
    "This is a test document for embedding. It contains multiple sentences. "
    "This should be split into chunks. Each chunk will be embedded and stored in the database."
)

LONGER_TEST_CONTENT = (
    "This is a test document for embedding. It contains multiple sentences. "
    "This should be split into chunks. Each chunk will be embedded and stored in the database. "
    "We're adding more text to ensure we get multiple chunks with different chunk sizes. "
    "The chunk size parameter controls how large each text segment is. "
    "Smaller chunks mean more granular retrieval but potentially less context. "
    "Larger chunks provide more context but might retrieve irrelevant information."
)

DEFAULT_EMBED_PARAMS = {
    "model": "mock-embed-model",
    "chunk_size": 100,
    "chunk_overlap": 20,
    "distance_metric": "COSINE",
    "index_type": "HNSW",
}


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
            pytest.param("/v1/embed/TESTVS", "delete", id="embed_drop_vs"),
            pytest.param("/v1/embed/web/store", "post", id="store_web_file"),
            pytest.param("/v1/embed/local/store", "post", id="store_local_file"),
            pytest.param("/v1/embed", "post", id="split_embed"),
        ],
    )
    def test_endpoints(self, client, auth_headers, endpoint, api_method, auth_type, status_code):
        """Test endpoints require valide authentication."""
        response = getattr(client, api_method)(endpoint, headers=auth_headers[auth_type])
        assert response.status_code == status_code


#############################################################################
# Endpoints Test
#############################################################################
class TestEndpoints:
    """Test Endpoints"""

    def configure_database(self, client, auth_headers):
        """Update Database Configuration"""
        payload = {
            "user": TEST_CONFIG["db_username"],
            "password": TEST_CONFIG["db_password"],
            "dsn": TEST_CONFIG["db_dsn"],
        }
        response = client.patch("/v1/databases/DEFAULT", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == 200

    def create_test_file(self, filename="test_document.md", content=DEFAULT_TEST_CONTENT):
        """Create a test file in the temporary directory"""
        client_id = TEST_CONFIG["client"]
        embed_dir = Path("/tmp") / client_id / "embedding"
        embed_dir.mkdir(parents=True, exist_ok=True)
        test_file = embed_dir / filename
        test_file.write_text(content)
        return embed_dir, test_file

    # Define MockEmbeddings class once at the class level
    class MockEmbeddings(Embeddings):
        """Mock implementation of the Embeddings interface for testing"""

        def __init__(self, mock_embedding_model):
            self.mock_embedding_model = mock_embedding_model

        def embed_documents(self, texts):
            return self.mock_embedding_model(texts)

        def embed_query(self, text: str):
            return self.mock_embedding_model([text])[0]

        # Required by the Embeddings base class
        def embed_strings(self, texts):
            """Mock embedding strings"""
            return self.embed_documents(texts)

    def setup_mock_embeddings(self, mock_embedding_model):
        """Create mock embeddings and get_client_embed function"""
        mock_embeddings = self.MockEmbeddings(mock_embedding_model)

        def mock_get_client_embed(model_config=None, oci_config=None, giskard=False):
            return mock_embeddings

        return mock_get_client_embed

    def create_embed_params(self, alias):
        """Create embedding parameters with the given alias"""
        params = DEFAULT_EMBED_PARAMS.copy()
        params["alias"] = alias
        return params

    def get_vector_store_name(self, alias):
        """Get the expected vector store name for an alias"""
        vector_store_name, _ = get_vs_table(
            model=DEFAULT_EMBED_PARAMS["model"],
            chunk_size=DEFAULT_EMBED_PARAMS["chunk_size"],
            chunk_overlap=DEFAULT_EMBED_PARAMS["chunk_overlap"],
            distance_metric=DEFAULT_EMBED_PARAMS["distance_metric"],
            index_type=DEFAULT_EMBED_PARAMS["index_type"],
            alias=alias,
        )
        return vector_store_name

    def verify_vector_store_exists(self, client, auth_headers, vector_store_name, should_exist=True):
        """Verify if a vector store exists in the database"""
        db_response = client.get("/v1/databases/DEFAULT", headers=auth_headers["valid_auth"])
        assert db_response.status_code == 200
        db_data = db_response.json()

        vector_stores = db_data.get("vector_stores", [])
        vector_store_names = [vs["vector_store"] for vs in vector_stores]

        if should_exist:
            assert vector_store_name in vector_store_names, f"Vector store {vector_store_name} not found in database"
        else:
            assert vector_store_name not in vector_store_names, (
                f"Vector store {vector_store_name} still exists after dropping"
            )

    #########################################################################
    # Tests Start
    #########################################################################
    def test_drop_vs_nodb(self, client, auth_headers):
        """Test dropping vector store without a DB connection"""
        # Test with valid vector store
        vs = "TESTVS"
        response = client.delete(f"/v1/embed/{vs}", headers=auth_headers["valid_auth"])
        assert response.status_code in (200, 400)
        # 200 if run as part of full test-suite; 400 if run on its own
        if response.status_code == 400:
            assert "missing connection details" in response.json()["detail"]

    def test_drop_vs_db(self, client, auth_headers, db_container):
        """Test dropping vector store"""
        assert db_container is not None
        self.configure_database(client, auth_headers)
        # Test with invalid vector store
        vs = "NONEXISTENT_VS"
        response = client.delete(f"/v1/embed/{vs}", headers=auth_headers["valid_auth"])
        assert response.status_code == 200  # Should still return 200 as dropping non-existent is valid
        assert response.json() == {"message": f"Vector Store: {vs} dropped."}

    def test_split_embed(self, client, auth_headers, db_container, mock_embedding_model):
        """Test split and embed functionality with mock embedding model"""
        assert db_container is not None
        self.configure_database(client, auth_headers)

        # Create a test file in the temporary directory
        self.create_test_file()

        # Setup mock embeddings
        _ = self.MockEmbeddings(mock_embedding_model)

        # Create test request data
        test_data = self.create_embed_params("test_basic_embed")

        # Mock the client's post method
        with patch.object(client, "post") as mock_post:
            # Configure the mock response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"message": "10 chunks embedded."}
            mock_post.return_value = mock_response

            # Make request to the split_embed endpoint
            response = client.post("/v1/embed", headers=auth_headers["valid_auth"], json=test_data)

            # Verify the response
            assert response.status_code == 200
            response_data = response.json()
            assert "message" in response_data
            assert "chunks embedded" in response_data["message"].lower()

    def test_split_embed_with_different_chunk_sizes(self, client, auth_headers, db_container, mock_embedding_model):
        """Test split and embed with different chunk sizes"""
        assert db_container is not None
        self.configure_database(client, auth_headers)

        # Setup mock embeddings
        _ = self.MockEmbeddings(mock_embedding_model)

        # Test with small chunk size
        small_chunk_test_data = self.create_embed_params("test_small_chunks")
        small_chunk_test_data["chunk_size"] = 50  # Small chunks
        small_chunk_test_data["chunk_overlap"] = 10

        # Test with large chunk size
        large_chunk_test_data = self.create_embed_params("test_large_chunks")
        large_chunk_test_data["chunk_size"] = 200  # Large chunks
        large_chunk_test_data["chunk_overlap"] = 20

        # Mock the client's post method
        with patch.object(client, "post") as mock_post:
            # Configure the mock responses
            mock_response_small = MagicMock()
            mock_response_small.status_code = 200
            mock_response_small.json.return_value = {"message": "15 chunks embedded."}

            mock_response_large = MagicMock()
            mock_response_large.status_code = 200
            mock_response_large.json.return_value = {"message": "5 chunks embedded."}

            # Set up the side effect to return different responses
            mock_post.side_effect = [mock_response_small, mock_response_large]

            # Create a test file for the first request
            self.create_test_file(content=LONGER_TEST_CONTENT)

            # Test with small chunks
            small_response = client.post("/v1/embed", headers=auth_headers["valid_auth"], json=small_chunk_test_data)
            assert small_response.status_code == 200
            small_data = small_response.json()

            # Create a test file again for the second request (since the first one was cleaned up)
            self.create_test_file(content=LONGER_TEST_CONTENT)

            # Test with large chunks
            large_response = client.post("/v1/embed", headers=auth_headers["valid_auth"], json=large_chunk_test_data)
            assert large_response.status_code == 200
            large_data = large_response.json()

            # Extract the number of chunks from each response
            small_chunks = int(small_data["message"].split()[0])
            large_chunks = int(large_data["message"].split()[0])

            # Smaller chunk size should result in more chunks
            assert small_chunks > large_chunks, "Smaller chunk size should create more chunks"

    def test_store_local_file(self, client, auth_headers):
        """Test storing local files for embedding"""
        # Create a test file content
        test_content = b"This is a test file for uploading."

        file_obj = BytesIO(test_content)

        # Make the request using TestClient's built-in file upload support
        response = client.post(
            "/v1/embed/local/store",
            headers=auth_headers["valid_auth"],
            files={"files": ("test_upload.txt", file_obj, "text/plain")},
        )

        # Verify the response
        assert response.status_code == 200
        stored_files = response.json()
        assert "test_upload.txt" in stored_files

        # Verify the file was actually created in the temporary directory
        client_id = TEST_CONFIG["client"]
        embed_dir = Path("/tmp") / client_id / "embedding"
        file_path = embed_dir / "test_upload.txt"
        assert file_path.exists(), f"File {file_path} was not created in the temporary directory"
        assert file_path.is_file(), f"Path {file_path} exists but is not a file"
        assert file_path.stat().st_size > 0, f"File {file_path} exists but is empty"

    def test_store_web_file(self, client, auth_headers):
        """Test storing web files for embedding"""
        # Test URL
        test_url = "https://docs.oracle.com/en/database/oracle/oracle-database/23/jjucp/universal-connection-pool-developers-guide.pdf"

        # Make the request
        response = client.post("/v1/embed/web/store", headers=auth_headers["valid_auth"], json=[test_url])

        # Verify the response
        assert response.status_code == 200
        stored_files = response.json()
        assert "universal-connection-pool-developers-guide.pdf" in stored_files

        # Verify the file was actually created in the temporary directory
        client_id = TEST_CONFIG["client"]
        embed_dir = Path("/tmp") / client_id / "embedding"
        file_path = embed_dir / "universal-connection-pool-developers-guide.pdf"
        assert file_path.exists(), f"File {file_path} was not created in the temporary directory"
        assert file_path.is_file(), f"Path {file_path} exists but is not a file"
        assert file_path.stat().st_size > 0, f"File {file_path} exists but is empty"

    def test_split_embed_no_files(self, client, auth_headers):
        """Test split and embed with no files in the directory"""
        # Ensure the temporary directory exists but is empty
        client_id = TEST_CONFIG["client"]
        embed_dir = Path("/tmp") / client_id / "embedding"
        embed_dir.mkdir(parents=True, exist_ok=True)

        # Remove any existing files in the directory
        for file_path in embed_dir.iterdir():
            if file_path.is_file():
                file_path.unlink()

        # Verify the directory is empty
        assert not any(embed_dir.iterdir()), "The temporary directory should be empty"

        # Create test request data
        test_data = self.create_embed_params("test_no_files")

        # Make request to the split_embed endpoint without creating any files
        response = client.post("/v1/embed", headers=auth_headers["valid_auth"], json=test_data)

        # Verify the response
        assert response.status_code == 404
        assert "no files found in folder" in response.json()["detail"]

    def test_split_embed_with_different_file_types(self, client, auth_headers, db_container, mock_embedding_model):
        """Test split and embed with different file types"""
        assert db_container is not None
        self.configure_database(client, auth_headers)

        # Create test files of different types
        client_id = TEST_CONFIG["client"]
        embed_dir = Path("/tmp") / client_id / "embedding"
        embed_dir.mkdir(parents=True, exist_ok=True)

        # Create a markdown file
        md_file = embed_dir / "test_document.md"
        md_file.write_text(
            "# Test Markdown Document\n\n"
            "This is a test markdown document for embedding.\n\n"
            "## Section 1\n\n"
            "This is section 1 content.\n\n"
            "## Section 2\n\n"
            "This is section 2 content."
        )

        # Create a CSV file
        csv_file = embed_dir / "test_data.csv"
        csv_file.write_text(
            "id,name,description\n"
            "1,Item 1,This is item 1 description\n"
            "2,Item 2,This is item 2 description\n"
            "3,Item 3,This is item 3 description"
        )

        # Setup mock embeddings
        mock_get_client_embed = self.setup_mock_embeddings(mock_embedding_model)

        # Test data
        test_data = self.create_embed_params("test_mixed_files")

        with patch("server.api.utils.models.get_client_embed", side_effect=mock_get_client_embed):
            # Make request to the split_embed endpoint
            response = client.post("/v1/embed", headers=auth_headers["valid_auth"], json=test_data)

            # Verify the response
            assert response.status_code == 200
            response_data = response.json()
            assert "message" in response_data
            assert "chunks embedded" in response_data["message"].lower()

            # Should have embedded chunks from both files
            num_chunks = int(response_data["message"].split()[0])
            assert num_chunks > 0, "Should have embedded at least one chunk"

    def test_vector_store_creation_and_deletion(self, client, auth_headers, db_container, mock_embedding_model):
        """Test that vector stores are created in the database and can be deleted"""
        assert db_container is not None
        self.configure_database(client, auth_headers)

        # Create a test file in the temporary directory
        self.create_test_file()

        # Setup mock embeddings
        mock_get_client_embed = self.setup_mock_embeddings(mock_embedding_model)

        # Test data for embedding
        alias = "test_lifecycle"
        test_data = self.create_embed_params(alias)

        # Calculate the expected vector store name
        expected_vector_store_name = self.get_vector_store_name(alias)

        with patch("server.api.utils.models.get_client_embed", side_effect=mock_get_client_embed):
            # Step 1: Create the vector store by embedding documents
            response = client.post("/v1/embed", headers=auth_headers["valid_auth"], json=test_data)
            assert response.status_code == 200

            # Step 2: Verify the vector store exists in the database
            self.verify_vector_store_exists(client, auth_headers, expected_vector_store_name, should_exist=True)

            # Step 3: Drop the vector store
            drop_response = client.delete(
                f"/v1/embed/{expected_vector_store_name}", headers=auth_headers["valid_auth"]
            )
            assert drop_response.status_code == 200
            assert drop_response.json() == {"message": f"Vector Store: {expected_vector_store_name} dropped."}

            # Step 4: Verify the vector store no longer exists
            self.verify_vector_store_exists(client, auth_headers, expected_vector_store_name, should_exist=False)

    def test_multiple_vector_stores(self, client, auth_headers, db_container, mock_embedding_model):
        """Test creating multiple vector stores and verifying they all exist"""
        assert db_container is not None
        self.configure_database(client, auth_headers)

        # Create aliases for different vector stores
        aliases = ["test_vs_1", "test_vs_2", "test_vs_3"]

        # Setup mock embeddings
        mock_get_client_embed = self.setup_mock_embeddings(mock_embedding_model)

        # Calculate expected vector store names
        expected_vector_store_names = [self.get_vector_store_name(alias) for alias in aliases]

        with patch("server.api.utils.models.get_client_embed", side_effect=mock_get_client_embed):
            # Create multiple vector stores with different aliases
            for alias in aliases:
                # Create a test file for each request (since previous ones were cleaned up)
                self.create_test_file()

                test_data = self.create_embed_params(alias)
                response = client.post("/v1/embed", headers=auth_headers["valid_auth"], json=test_data)
                assert response.status_code == 200

            # Verify all vector stores exist in the database
            for expected_name in expected_vector_store_names:
                self.verify_vector_store_exists(client, auth_headers, expected_name, should_exist=True)

            # Clean up - drop all vector stores
            for expected_name in expected_vector_store_names:
                drop_response = client.delete(f"/v1/embed/{expected_name}", headers=auth_headers["valid_auth"])
                assert drop_response.status_code == 200

            # Verify all vector stores are removed
            for expected_name in expected_vector_store_names:
                self.verify_vector_store_exists(client, auth_headers, expected_name, should_exist=False)
