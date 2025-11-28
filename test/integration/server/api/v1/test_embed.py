"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/embed.py

Tests the embedding and vector store endpoints through the full API stack.
These endpoints require authentication.
"""


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
