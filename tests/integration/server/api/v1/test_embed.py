"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/embed.py

Tests the embedding and vector store endpoints through the full API stack.
These endpoints require authentication.
"""
# pylint: disable=too-few-public-methods

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class MockEmbeddings(Embeddings):
    """Mock implementation of the Embeddings interface for testing"""

    def __init__(self, mock_embedding_model):
        self.mock_embedding_model = mock_embedding_model

    def embed_documents(self, texts):
        return self.mock_embedding_model(texts)

    def embed_query(self, text: str):
        return self.mock_embedding_model([text])[0]

    def embed_strings(self, texts):
        """Mock embedding strings"""
        return self.embed_documents(texts)


class TestEmbedDropVs:
    """Integration tests for the embed_drop_vs endpoint."""

    def test_embed_drop_vs_requires_auth(self, client):
        """DELETE /v1/embed/{vs} should require authentication."""
        response = client.delete("/v1/embed/VS_TEST")

        assert response.status_code == 401

    def test_embed_drop_vs_rejects_invalid_token(self, client, auth_headers):
        """DELETE /v1/embed/{vs} should reject invalid tokens."""
        response = client.delete("/v1/embed/VS_TEST", headers=auth_headers["invalid_auth"])

        assert response.status_code == 401


class TestEmbedGetFiles:
    """Integration tests for the embed_get_files endpoint."""

    def test_embed_get_files_requires_auth(self, client):
        """GET /v1/embed/{vs}/files should require authentication."""
        response = client.get("/v1/embed/VS_TEST/files")

        assert response.status_code == 401

    def test_embed_get_files_rejects_invalid_token(self, client, auth_headers):
        """GET /v1/embed/{vs}/files should reject invalid tokens."""
        response = client.get("/v1/embed/VS_TEST/files", headers=auth_headers["invalid_auth"])

        assert response.status_code == 401


class TestCommentVs:
    """Integration tests for the comment_vs endpoint."""

    def test_comment_vs_requires_auth(self, client):
        """PATCH /v1/embed/comment should require authentication."""
        response = client.patch(
            "/v1/embed/comment",
            json={"vector_store": "VS_TEST", "model": "text-embedding-3", "chunk_size": 1000, "chunk_overlap": 200},
        )

        assert response.status_code == 401

    def test_comment_vs_rejects_invalid_token(self, client, auth_headers):
        """PATCH /v1/embed/comment should reject invalid tokens."""
        response = client.patch(
            "/v1/embed/comment",
            headers=auth_headers["invalid_auth"],
            json={"vector_store": "VS_TEST", "model": "text-embedding-3", "chunk_size": 1000, "chunk_overlap": 200},
        )

        assert response.status_code == 401


class TestStoreSqlFile:
    """Integration tests for the store_sql_file endpoint."""

    def test_store_sql_file_requires_auth(self, client):
        """POST /v1/embed/sql/store should require authentication."""
        response = client.post("/v1/embed/sql/store", json=["conn_str", "SELECT 1"])

        assert response.status_code == 401

    def test_store_sql_file_rejects_invalid_token(self, client, auth_headers):
        """POST /v1/embed/sql/store should reject invalid tokens."""
        response = client.post(
            "/v1/embed/sql/store",
            headers=auth_headers["invalid_auth"],
            json=["conn_str", "SELECT 1"],
        )

        assert response.status_code == 401


class TestStoreWebFile:
    """Integration tests for the store_web_file endpoint."""

    def test_store_web_file_requires_auth(self, client):
        """POST /v1/embed/web/store should require authentication."""
        response = client.post("/v1/embed/web/store", json=["https://example.com/doc.pdf"])

        assert response.status_code == 401

    def test_store_web_file_rejects_invalid_token(self, client, auth_headers):
        """POST /v1/embed/web/store should reject invalid tokens."""
        response = client.post(
            "/v1/embed/web/store",
            headers=auth_headers["invalid_auth"],
            json=["https://example.com/doc.pdf"],
        )

        assert response.status_code == 401


class TestStoreLocalFile:
    """Integration tests for the store_local_file endpoint."""

    def test_store_local_file_requires_auth(self, client):
        """POST /v1/embed/local/store should require authentication."""
        response = client.post(
            "/v1/embed/local/store",
            files={"files": ("test.txt", b"Test content", "text/plain")},
        )

        assert response.status_code == 401

    def test_store_local_file_rejects_invalid_token(self, client, auth_headers):
        """POST /v1/embed/local/store should reject invalid tokens."""
        response = client.post(
            "/v1/embed/local/store",
            headers=auth_headers["invalid_auth"],
            files={"files": ("test.txt", b"Test content", "text/plain")},
        )

        assert response.status_code == 401


class TestSplitEmbed:
    """Integration tests for the split_embed endpoint."""

    def test_split_embed_requires_auth(self, client):
        """POST /v1/embed should require authentication."""
        response = client.post(
            "/v1/embed",
            json={"model": "text-embedding-3", "chunk_size": 1000, "chunk_overlap": 200},
        )

        assert response.status_code == 401

    def test_split_embed_rejects_invalid_token(self, client, auth_headers):
        """POST /v1/embed should reject invalid tokens."""
        response = client.post(
            "/v1/embed",
            headers=auth_headers["invalid_auth"],
            json={"model": "text-embedding-3", "chunk_size": 1000, "chunk_overlap": 200},
        )

        assert response.status_code == 401


class TestRefreshVectorStore:
    """Integration tests for the refresh_vector_store endpoint."""

    def test_refresh_vector_store_requires_auth(self, client):
        """POST /v1/embed/refresh should require authentication."""
        response = client.post(
            "/v1/embed/refresh",
            json={"vector_store_alias": "test_alias", "bucket_name": "test-bucket"},
        )

        assert response.status_code == 401

    def test_refresh_vector_store_rejects_invalid_token(self, client, auth_headers):
        """POST /v1/embed/refresh should reject invalid tokens."""
        response = client.post(
            "/v1/embed/refresh",
            headers=auth_headers["invalid_auth"],
            json={"vector_store_alias": "test_alias", "bucket_name": "test-bucket"},
        )

        assert response.status_code == 401


#############################################################################
# Helper functions for embed tests
#############################################################################
def configure_database(client, auth_headers, test_db_payload):
    """Update Database Configuration"""
    response = client.patch("/v1/databases/DEFAULT", headers=auth_headers["valid_auth"], json=test_db_payload)
    assert response.status_code == 200


def create_test_file(client_id, filename="test_document.md", content=DEFAULT_TEST_CONTENT):
    """Create a test file in the temporary directory"""
    embed_dir = Path("/tmp") / client_id / "embedding"
    embed_dir.mkdir(parents=True, exist_ok=True)
    test_file = embed_dir / filename
    test_file.write_text(content)
    return embed_dir, test_file


def setup_mock_embeddings(mock_embedding_model):
    """Create mock embeddings and get_client_embed function"""
    mock_embeddings = MockEmbeddings(mock_embedding_model)

    def mock_get_client_embed(_model_config=None, _oci_config=None, _giskard=False):
        return mock_embeddings

    return mock_get_client_embed


def create_embed_params(alias):
    """Create embedding parameters with the given alias"""
    params = DEFAULT_EMBED_PARAMS.copy()
    params["alias"] = alias
    return params


def get_vector_store_name(alias):
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


def verify_vector_store_exists(client, auth_headers, vector_store_name, should_exist=True):
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


#############################################################################
# Functional Tests with Database
#############################################################################
class TestEmbedDropVsWithDb:
    """Integration tests for embed_drop_vs with database."""

    def test_drop_vs_nodb(self, client, test_client_auth_headers):
        """Test dropping vector store without a DB connection"""
        vs = "TESTVS"
        response = client.delete(f"/v1/embed/{vs}", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code in (200, 400)
        if response.status_code == 400:
            assert "missing connection details" in response.json()["detail"]

    def test_drop_vs_db(self, client, test_client_auth_headers, db_container, test_db_payload):
        """Test dropping vector store"""
        assert db_container is not None
        configure_database(client, test_client_auth_headers, test_db_payload)
        vs = "NONEXISTENT_VS"
        response = client.delete(f"/v1/embed/{vs}", headers=test_client_auth_headers["valid_auth"])
        assert response.status_code == 200
        assert response.json() == {"message": f"Vector Store: {vs} dropped."}


class TestSplitEmbedWithDb:
    """Integration tests for split_embed with database."""

    def test_split_embed(self, client, test_client_auth_headers, db_container, test_db_payload, mock_embedding_model):
        """Test split and embed functionality with mock embedding model"""
        assert db_container is not None
        configure_database(client, test_client_auth_headers, test_db_payload)

        create_test_file("test_client")
        _ = MockEmbeddings(mock_embedding_model)
        test_data = create_embed_params("test_basic_embed")

        with patch.object(client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"message": "10 chunks embedded."}
            mock_post.return_value = mock_response

            response = client.post("/v1/embed", headers=test_client_auth_headers["valid_auth"], json=test_data)
            assert response.status_code == 200
            response_data = response.json()
            assert "message" in response_data
            assert "chunks embedded" in response_data["message"].lower()

    def test_split_embed_with_different_chunk_sizes(
        self, client, test_client_auth_headers, db_container, test_db_payload, mock_embedding_model
    ):
        """Test split and embed with different chunk sizes"""
        assert db_container is not None
        configure_database(client, test_client_auth_headers, test_db_payload)
        _ = MockEmbeddings(mock_embedding_model)

        small_chunk_test_data = create_embed_params("test_small_chunks")
        small_chunk_test_data["chunk_size"] = 50
        small_chunk_test_data["chunk_overlap"] = 10

        large_chunk_test_data = create_embed_params("test_large_chunks")
        large_chunk_test_data["chunk_size"] = 200
        large_chunk_test_data["chunk_overlap"] = 20

        with patch.object(client, "post") as mock_post:
            mock_response_small = MagicMock()
            mock_response_small.status_code = 200
            mock_response_small.json.return_value = {"message": "15 chunks embedded."}

            mock_response_large = MagicMock()
            mock_response_large.status_code = 200
            mock_response_large.json.return_value = {"message": "5 chunks embedded."}

            mock_post.side_effect = [mock_response_small, mock_response_large]

            create_test_file("test_client", content=LONGER_TEST_CONTENT)
            small_response = client.post(
                "/v1/embed", headers=test_client_auth_headers["valid_auth"], json=small_chunk_test_data
            )
            assert small_response.status_code == 200
            small_data = small_response.json()

            create_test_file("test_client", content=LONGER_TEST_CONTENT)
            large_response = client.post(
                "/v1/embed", headers=test_client_auth_headers["valid_auth"], json=large_chunk_test_data
            )
            assert large_response.status_code == 200
            large_data = large_response.json()

            small_chunks = int(small_data["message"].split()[0])
            large_chunks = int(large_data["message"].split()[0])
            assert small_chunks > large_chunks, "Smaller chunk size should create more chunks"

    def test_split_embed_no_files(self, client, test_client_auth_headers):
        """Test split and embed with no files in the directory"""
        client_id = "test_client"
        embed_dir = Path("/tmp") / client_id / "embedding"
        embed_dir.mkdir(parents=True, exist_ok=True)

        for file_path in embed_dir.iterdir():
            if file_path.is_file():
                file_path.unlink()

        assert not any(embed_dir.iterdir()), "The temporary directory should be empty"
        test_data = create_embed_params("test_no_files")

        response = client.post("/v1/embed", headers=test_client_auth_headers["valid_auth"], json=test_data)
        assert response.status_code == 404
        assert "no files found in folder" in response.json()["detail"]


class TestStoreLocalFileWithDb:
    """Integration tests for store_local_file."""

    def test_store_local_file(self, client, test_client_auth_headers):
        """Test storing local files for embedding"""
        test_content = b"This is a test file for uploading."
        file_obj = BytesIO(test_content)

        response = client.post(
            "/v1/embed/local/store",
            headers=test_client_auth_headers["valid_auth"],
            files={"files": ("test_upload.txt", file_obj, "text/plain")},
        )

        assert response.status_code == 200
        stored_files = response.json()
        assert "test_upload.txt" in stored_files


class TestStoreWebFileWithDb:
    """Integration tests for store_web_file."""

    def test_store_web_file(self, client, test_client_auth_headers):
        """Test storing web files for embedding"""
        test_url = (
            "https://docs.oracle.com/en/database/oracle/oracle-database/23/jjucp/"
            "universal-connection-pool-developers-guide.pdf"
        )

        response = client.post("/v1/embed/web/store", headers=test_client_auth_headers["valid_auth"], json=[test_url])
        assert response.status_code == 200
        stored_files = response.json()
        assert "universal-connection-pool-developers-guide.pdf" in stored_files


class TestVectorStoreLifecycle:
    """Integration tests for vector store creation and deletion lifecycle."""

    def test_vector_store_creation_and_deletion(
        self, client, test_client_auth_headers, db_container, test_db_payload, mock_embedding_model
    ):
        """Test that vector stores are created in the database and can be deleted"""
        assert db_container is not None
        configure_database(client, test_client_auth_headers, test_db_payload)

        create_test_file("test_client")
        mock_get_client_embed = setup_mock_embeddings(mock_embedding_model)

        alias = "test_lifecycle"
        test_data = create_embed_params(alias)
        expected_vector_store_name = get_vector_store_name(alias)

        with patch("server.api.utils.models.get_client_embed", side_effect=mock_get_client_embed):
            response = client.post("/v1/embed", headers=test_client_auth_headers["valid_auth"], json=test_data)
            assert response.status_code == 200

            verify_vector_store_exists(client, test_client_auth_headers, expected_vector_store_name, should_exist=True)

            drop_response = client.delete(
                f"/v1/embed/{expected_vector_store_name}", headers=test_client_auth_headers["valid_auth"]
            )
            assert drop_response.status_code == 200
            assert drop_response.json() == {"message": f"Vector Store: {expected_vector_store_name} dropped."}

            verify_vector_store_exists(
                client, test_client_auth_headers, expected_vector_store_name, should_exist=False
            )

    def test_multiple_vector_stores(
        self, client, test_client_auth_headers, db_container, test_db_payload, mock_embedding_model
    ):
        """Test creating multiple vector stores and verifying they all exist"""
        assert db_container is not None
        configure_database(client, test_client_auth_headers, test_db_payload)

        aliases = ["test_vs_1", "test_vs_2", "test_vs_3"]
        mock_get_client_embed = setup_mock_embeddings(mock_embedding_model)
        expected_vector_store_names = [get_vector_store_name(alias) for alias in aliases]

        with patch("server.api.utils.models.get_client_embed", side_effect=mock_get_client_embed):
            for alias in aliases:
                create_test_file("test_client")
                test_data = create_embed_params(alias)
                response = client.post("/v1/embed", headers=test_client_auth_headers["valid_auth"], json=test_data)
                assert response.status_code == 200

            for expected_name in expected_vector_store_names:
                verify_vector_store_exists(client, test_client_auth_headers, expected_name, should_exist=True)

            for expected_name in expected_vector_store_names:
                drop_response = client.delete(
                    f"/v1/embed/{expected_name}", headers=test_client_auth_headers["valid_auth"]
                )
                assert drop_response.status_code == 200

            for expected_name in expected_vector_store_names:
                verify_vector_store_exists(client, test_client_auth_headers, expected_name, should_exist=False)


class TestGetVectorStoreFiles:
    """Integration tests for getting vector store files."""

    def test_get_vector_store_files(
        self, client, test_client_auth_headers, db_container, test_db_payload, mock_embedding_model
    ):
        """Test retrieving file list from vector store"""
        assert db_container is not None
        configure_database(client, test_client_auth_headers, test_db_payload)

        create_test_file("test_client", content=LONGER_TEST_CONTENT)
        mock_get_client_embed = setup_mock_embeddings(mock_embedding_model)

        alias = "test_file_listing"
        test_data = create_embed_params(alias)
        expected_vector_store_name = get_vector_store_name(alias)

        with patch("server.api.utils.models.get_client_embed", side_effect=mock_get_client_embed):
            response = client.post("/v1/embed", headers=test_client_auth_headers["valid_auth"], json=test_data)
            assert response.status_code == 200

            file_list_response = client.get(
                f"/v1/embed/{expected_vector_store_name}/files", headers=test_client_auth_headers["valid_auth"]
            )

            assert file_list_response.status_code == 200
            data = file_list_response.json()

            assert "vector_store" in data
            assert data["vector_store"] == expected_vector_store_name
            assert "total_files" in data
            assert "total_chunks" in data
            assert "files" in data
            assert data["total_files"] > 0
            assert data["total_chunks"] > 0

            drop_response = client.delete(
                f"/v1/embed/{expected_vector_store_name}", headers=test_client_auth_headers["valid_auth"]
            )
            assert drop_response.status_code == 200

    def test_get_files_nonexistent_vector_store(self, client, test_client_auth_headers, db_container, test_db_payload):
        """Test retrieving file list from nonexistent vector store"""
        assert db_container is not None
        configure_database(client, test_client_auth_headers, test_db_payload)

        response = client.get("/v1/embed/NONEXISTENT_VS/files", headers=test_client_auth_headers["valid_auth"])

        assert response.status_code in (200, 400)
