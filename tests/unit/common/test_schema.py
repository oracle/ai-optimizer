"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for common/schema.py

Tests Pydantic models, field validation, and utility methods.
"""
# pylint: disable=too-few-public-methods

import time
from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError

from langchain_core.messages import ChatMessage

from common.schema import (
    # Database models
    DatabaseVectorStorage,
    VectorStoreRefreshRequest,
    VectorStoreRefreshStatus,
    DatabaseAuth,
    Database,
    # Model models
    LanguageModelParameters,
    EmbeddingModelParameters,
    ModelAccess,
    Model,
    # OCI models
    OracleResource,
    OracleCloudSettings,
    # Prompt models
    MCPPrompt,
    # Settings models
    VectorSearchSettings,
    Settings,
    # Configuration
    Configuration,
    # Completions
    ChatRequest,
    # Testbed
    QASets,
    QASetData,
    Evaluation,
    EvaluationReport,
    # Types
    ClientIdType,
    DatabaseNameType,
    VectorStoreTableType,
    ModelIdType,
    ModelProviderType,
    ModelTypeType,
    ModelEnabledType,
    OCIProfileType,
    OCIResourceOCID,
)


class TestDatabaseVectorStorage:
    """Tests for DatabaseVectorStorage model."""

    def test_default_values(self):
        """DatabaseVectorStorage should have correct defaults."""
        storage = DatabaseVectorStorage()

        assert storage.vector_store is None
        assert storage.alias is None
        assert storage.description is None
        assert storage.model is None
        assert storage.chunk_size == 0
        assert storage.chunk_overlap == 0
        assert storage.distance_metric is None
        assert storage.index_type is None

    def test_with_all_values(self):
        """DatabaseVectorStorage should accept all valid values."""
        storage = DatabaseVectorStorage(
            vector_store="TEST_VS",
            alias="test_alias",
            description="Test description",
            model="text-embedding-ada-002",
            chunk_size=1000,
            chunk_overlap=100,
            distance_metric="COSINE",
            index_type="HNSW",
        )

        assert storage.vector_store == "TEST_VS"
        assert storage.alias == "test_alias"
        assert storage.description == "Test description"
        assert storage.model == "text-embedding-ada-002"
        assert storage.chunk_size == 1000
        assert storage.chunk_overlap == 100
        assert storage.distance_metric == "COSINE"
        assert storage.index_type == "HNSW"

    def test_distance_metric_literals(self):
        """DatabaseVectorStorage should only accept valid distance metrics."""
        for metric in ["COSINE", "EUCLIDEAN_DISTANCE", "DOT_PRODUCT"]:
            storage = DatabaseVectorStorage(distance_metric=metric)
            assert storage.distance_metric == metric

    def test_index_type_literals(self):
        """DatabaseVectorStorage should only accept valid index types."""
        for index_type in ["HNSW", "IVF"]:
            storage = DatabaseVectorStorage(index_type=index_type)
            assert storage.index_type == index_type


class TestVectorStoreRefreshRequest:
    """Tests for VectorStoreRefreshRequest model."""

    def test_required_fields(self):
        """VectorStoreRefreshRequest should require vector_store_alias and bucket_name."""
        with pytest.raises(ValidationError):
            VectorStoreRefreshRequest()

        request = VectorStoreRefreshRequest(
            vector_store_alias="test_alias",
            bucket_name="test-bucket",
        )
        assert request.vector_store_alias == "test_alias"
        assert request.bucket_name == "test-bucket"

    def test_default_values(self):
        """VectorStoreRefreshRequest should have correct defaults."""
        request = VectorStoreRefreshRequest(
            vector_store_alias="test",
            bucket_name="bucket",
        )
        assert request.auth_profile == "DEFAULT"
        assert request.rate_limit == 0


class TestVectorStoreRefreshStatus:
    """Tests for VectorStoreRefreshStatus model."""

    def test_required_fields(self):
        """VectorStoreRefreshStatus should require status and message."""
        with pytest.raises(ValidationError):
            VectorStoreRefreshStatus()

        status = VectorStoreRefreshStatus(
            status="processing",
            message="In progress",
        )
        assert status.status == "processing"

    def test_status_literals(self):
        """VectorStoreRefreshStatus should only accept valid status values."""
        for valid_status in ["processing", "completed", "failed"]:
            status = VectorStoreRefreshStatus(status=valid_status, message="test")
            assert status.status == valid_status

    def test_default_values(self):
        """VectorStoreRefreshStatus should have correct defaults."""
        status = VectorStoreRefreshStatus(status="completed", message="Done")
        assert status.processed_files == 0
        assert status.new_files == 0
        assert status.updated_files == 0
        assert status.total_chunks == 0
        assert status.total_chunks_in_store == 0
        assert status.errors == []


class TestDatabaseAuth:
    """Tests for DatabaseAuth model."""

    def test_default_values(self):
        """DatabaseAuth should have correct defaults."""
        auth = DatabaseAuth()

        assert auth.user is None
        assert auth.password is None
        assert auth.dsn is None
        assert auth.wallet_password is None
        assert auth.wallet_location is None
        assert auth.config_dir == "tns_admin"
        assert auth.tcp_connect_timeout == 5

    def test_sensitive_fields_marked(self):
        """DatabaseAuth sensitive fields should be marked."""
        password_field = DatabaseAuth.model_fields.get("password")
        assert password_field.json_schema_extra.get("sensitive") is True

        wallet_password_field = DatabaseAuth.model_fields.get("wallet_password")
        assert wallet_password_field.json_schema_extra.get("sensitive") is True


class TestDatabase:
    """Tests for Database model."""

    def test_inherits_from_database_auth(self):
        """Database should inherit from DatabaseAuth."""
        assert issubclass(Database, DatabaseAuth)

    def test_default_values(self):
        """Database should have correct defaults."""
        db = Database()

        assert db.name == "DEFAULT"
        assert db.connected is False
        assert db.vector_stores == []
        assert db.user is None  # Inherited from DatabaseAuth

    def test_connection_property(self):
        """Database connection property should work correctly."""
        db = Database()
        assert db.connection is None

        mock_conn = MagicMock()
        db.set_connection(mock_conn)
        assert db.connection == mock_conn

    def test_readonly_fields_marked(self):
        """Database readonly fields should be marked."""
        connected_field = Database.model_fields["connected"]
        assert connected_field.json_schema_extra.get("readOnly") is True

        vector_stores_field = Database.model_fields["vector_stores"]
        assert vector_stores_field.json_schema_extra.get("readOnly") is True


class TestLanguageModelParameters:
    """Tests for LanguageModelParameters model."""

    def test_default_values(self):
        """LanguageModelParameters should have correct defaults."""
        params = LanguageModelParameters()

        assert params.max_input_tokens is None
        assert params.frequency_penalty == 0.00
        assert params.max_tokens == 4096
        assert params.presence_penalty == 0.00
        assert params.temperature == 0.50
        assert params.top_p == 1.00


class TestEmbeddingModelParameters:
    """Tests for EmbeddingModelParameters model."""

    def test_default_values(self):
        """EmbeddingModelParameters should have correct defaults."""
        params = EmbeddingModelParameters()

        assert params.max_chunk_size == 8192


class TestModelAccess:
    """Tests for ModelAccess model."""

    def test_default_values(self):
        """ModelAccess should have correct defaults."""
        access = ModelAccess()

        assert access.enabled is False
        assert access.api_base is None
        assert access.api_key is None

    def test_sensitive_field_marked(self):
        """ModelAccess api_key should be marked sensitive."""
        api_key_field = ModelAccess.model_fields.get("api_key")
        assert api_key_field.json_schema_extra.get("sensitive") is True


class TestModel:
    """Tests for Model model."""

    def test_required_fields(self):
        """Model should require id, type, and provider."""
        with pytest.raises(ValidationError):
            Model()

        model = Model(id="gpt-4", type="ll", provider="openai")
        assert model.id == "gpt-4"
        assert model.type == "ll"
        assert model.provider == "openai"

    def test_default_values(self):
        """Model should have correct defaults."""
        model = Model(id="test-model", type="embed", provider="test")

        assert model.object == "model"
        assert model.owned_by == "aioptimizer"
        assert model.enabled is False

    def test_created_timestamp(self):
        """Model created should be a Unix timestamp."""
        before = int(time.time())
        model = Model(id="test", type="ll", provider="test")
        after = int(time.time())

        assert before <= model.created <= after

    def test_type_literals(self):
        """Model type should only accept valid values."""
        for model_type in ["ll", "embed", "rerank"]:
            model = Model(id="test", type=model_type, provider="test")
            assert model.type == model_type

    def test_id_min_length(self):
        """Model id should have minimum length of 1."""
        with pytest.raises(ValidationError):
            Model(id="", type="ll", provider="openai")


class TestOracleResource:
    """Tests for OracleResource model."""

    def test_valid_ocid(self):
        """OracleResource should accept valid OCIDs."""
        valid_ocid = "ocid1.compartment.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        resource = OracleResource(ocid=valid_ocid)
        assert resource.ocid == valid_ocid

    def test_invalid_ocid_rejected(self):
        """OracleResource should reject invalid OCIDs."""
        with pytest.raises(ValidationError):
            OracleResource(ocid="invalid-ocid")


class TestOracleCloudSettings:
    """Tests for OracleCloudSettings model."""

    def test_default_values(self):
        """OracleCloudSettings should have correct defaults."""
        settings = OracleCloudSettings()

        assert settings.auth_profile == "DEFAULT"
        assert settings.namespace is None
        assert settings.user is None
        assert settings.security_token_file is None
        assert settings.authentication == "api_key"
        assert settings.genai_compartment_id is None
        assert settings.genai_region is None

    def test_authentication_literals(self):
        """OracleCloudSettings authentication should only accept valid values."""
        valid_auths = ["api_key", "instance_principal", "oke_workload_identity", "security_token"]
        for auth in valid_auths:
            settings = OracleCloudSettings(authentication=auth)
            assert settings.authentication == auth

    def test_allows_extra_fields(self):
        """OracleCloudSettings should allow extra fields."""
        settings = OracleCloudSettings(extra_field="extra_value")
        assert settings.extra_field == "extra_value"


class TestMCPPrompt:
    """Tests for MCPPrompt model."""

    def test_required_fields(self):
        """MCPPrompt should require name, title, and text."""
        with pytest.raises(ValidationError):
            MCPPrompt()

        prompt = MCPPrompt(name="test_prompt", title="Test", text="Hello")
        assert prompt.name == "test_prompt"

    def test_default_values(self):
        """MCPPrompt should have correct defaults."""
        prompt = MCPPrompt(name="test", title="Test", text="Content")

        assert prompt.description == ""
        assert prompt.tags == []


class TestSettings:
    """Tests for Settings model."""

    def test_required_client(self):
        """Settings should require client."""
        with pytest.raises(ValidationError):
            Settings()

        settings = Settings(client="test_client")
        assert settings.client == "test_client"

    def test_client_min_length(self):
        """Settings client should have minimum length of 1."""
        with pytest.raises(ValidationError):
            Settings(client="")

    def test_default_values(self):
        """Settings should have correct defaults."""
        settings = Settings(client="test")

        assert settings.ll_model is not None
        assert settings.oci is not None
        assert settings.database is not None
        assert settings.tools_enabled == []
        assert settings.vector_search is not None
        assert settings.testbed is not None


class TestVectorSearchSettings:
    """Tests for VectorSearchSettings model."""

    def test_default_values(self):
        """VectorSearchSettings should have correct defaults."""
        settings = VectorSearchSettings()

        assert settings.discovery is True
        assert settings.rephrase is True
        assert settings.grade is True
        assert settings.search_type == "Similarity"
        assert settings.top_k == 8
        assert settings.score_threshold == 0.65
        assert settings.fetch_k == 20
        assert settings.lambda_mult == 0.5

    def test_search_type_literals(self):
        """VectorSearchSettings search_type should only accept valid values."""
        valid_types = ["Similarity", "Maximal Marginal Relevance"]
        for search_type in valid_types:
            settings = VectorSearchSettings(search_type=search_type)
            assert settings.search_type == search_type

    def test_top_k_validation(self):
        """VectorSearchSettings top_k should be between 1 and 10000."""
        # Valid
        VectorSearchSettings(top_k=1)
        VectorSearchSettings(top_k=10000)

        # Invalid
        with pytest.raises(ValidationError):
            VectorSearchSettings(top_k=0)
        with pytest.raises(ValidationError):
            VectorSearchSettings(top_k=10001)

    def test_score_threshold_validation(self):
        """VectorSearchSettings score_threshold should be between 0.0 and 1.0."""
        VectorSearchSettings(score_threshold=0.0)
        VectorSearchSettings(score_threshold=1.0)

        with pytest.raises(ValidationError):
            VectorSearchSettings(score_threshold=-0.1)
        with pytest.raises(ValidationError):
            VectorSearchSettings(score_threshold=1.1)


class TestConfiguration:
    """Tests for Configuration model."""

    def test_required_client_settings(self):
        """Configuration should require client_settings."""
        with pytest.raises(ValidationError):
            Configuration()

        config = Configuration(client_settings=Settings(client="test"))
        assert config.client_settings.client == "test"

    def test_optional_config_lists(self):
        """Configuration config lists should be optional."""
        config = Configuration(client_settings=Settings(client="test"))

        assert config.database_configs is None
        assert config.model_configs is None
        assert config.oci_configs is None
        assert config.prompt_configs is None

    def test_model_dump_public_excludes_sensitive(self):
        """model_dump_public should exclude sensitive fields by default."""
        db = Database(name="TEST", user="user", password="secret123", dsn="localhost")
        config = Configuration(
            client_settings=Settings(client="test"),
            database_configs=[db],
        )

        dumped = config.model_dump_public(incl_sensitive=False)
        assert "password" not in dumped["database_configs"][0]

    def test_model_dump_public_includes_sensitive_when_requested(self):
        """model_dump_public should include sensitive fields when requested."""
        db = Database(name="TEST", user="user", password="secret123", dsn="localhost")
        config = Configuration(
            client_settings=Settings(client="test"),
            database_configs=[db],
        )

        dumped = config.model_dump_public(incl_sensitive=True)
        assert dumped["database_configs"][0]["password"] == "secret123"

    def test_model_dump_public_excludes_readonly(self):
        """model_dump_public should exclude readonly fields by default."""
        db = Database(name="TEST", connected=True)
        config = Configuration(
            client_settings=Settings(client="test"),
            database_configs=[db],
        )

        dumped = config.model_dump_public(incl_readonly=False)
        assert "connected" not in dumped["database_configs"][0]
        assert "vector_stores" not in dumped["database_configs"][0]

    def test_model_dump_public_includes_readonly_when_requested(self):
        """model_dump_public should include readonly fields when requested."""
        db = Database(name="TEST", connected=True)
        config = Configuration(
            client_settings=Settings(client="test"),
            database_configs=[db],
        )

        dumped = config.model_dump_public(incl_readonly=True)
        assert dumped["database_configs"][0]["connected"] is True

    def test_recursive_dump_handles_nested_lists(self):
        """recursive_dump should handle nested lists correctly."""
        storage = DatabaseVectorStorage(vector_store="VS1", alias="test")
        db = Database(name="TEST", vector_stores=[storage])
        config = Configuration(
            client_settings=Settings(client="test"),
            database_configs=[db],
        )

        dumped = config.model_dump_public(incl_readonly=True)
        assert dumped["database_configs"][0]["vector_stores"][0]["alias"] == "test"

    def test_recursive_dump_handles_dicts(self):
        """recursive_dump should handle dicts correctly."""
        # OracleCloudSettings allows extra fields
        oci = OracleCloudSettings(auth_profile="TEST", extra_key="extra_value")
        config = Configuration(
            client_settings=Settings(client="test"),
            oci_configs=[oci],
        )

        dumped = config.model_dump_public()
        assert dumped["oci_configs"][0]["extra_key"] == "extra_value"


class TestChatRequest:
    """Tests for ChatRequest model."""

    def test_required_messages(self):
        """ChatRequest should require messages."""
        with pytest.raises(ValidationError):
            ChatRequest()

    def test_inherits_language_model_parameters(self):
        """ChatRequest should inherit from LanguageModelParameters."""
        assert issubclass(ChatRequest, LanguageModelParameters)

    def test_default_model_is_none(self):
        """ChatRequest model should default to None."""
        request = ChatRequest(messages=[ChatMessage(role="user", content="Hello")])
        assert request.model is None


class TestQAModels:
    """Tests for QA testbed-related models."""

    def test_qa_sets_required_fields(self):
        """QASets should require tid, name, and created."""
        with pytest.raises(ValidationError):
            QASets()

        qa_set = QASets(tid="123", name="Test Set", created="2024-01-01")
        assert qa_set.tid == "123"

    def test_qa_set_data_required_fields(self):
        """QASetData should require qa_data."""
        with pytest.raises(ValidationError):
            QASetData()

        qa = QASetData(qa_data=[{"q": "question", "a": "answer"}])
        assert len(qa.qa_data) == 1

    def test_evaluation_required_fields(self):
        """Evaluation should require eid, evaluated, and correctness."""
        with pytest.raises(ValidationError):
            Evaluation()

        evaluation = Evaluation(eid="eval1", evaluated="2024-01-01", correctness=0.95)
        assert evaluation.correctness == 0.95

    def test_evaluation_report_inherits_evaluation(self):
        """EvaluationReport should inherit from Evaluation."""
        assert issubclass(EvaluationReport, Evaluation)


class TestTypeAliases:
    """Tests for type aliases."""

    def test_client_id_type(self):
        """ClientIdType should be the annotation for Settings.client."""
        assert ClientIdType == Settings.__annotations__["client"]

    def test_database_name_type(self):
        """DatabaseNameType should be the annotation for Database.name."""
        assert DatabaseNameType == Database.__annotations__["name"]

    def test_vector_store_table_type(self):
        """VectorStoreTableType should be the annotation for DatabaseVectorStorage.vector_store."""
        assert VectorStoreTableType == DatabaseVectorStorage.__annotations__["vector_store"]

    def test_model_id_type(self):
        """ModelIdType should be the annotation for Model.id."""
        assert ModelIdType == Model.__annotations__["id"]

    def test_model_provider_type(self):
        """ModelProviderType should be the annotation for Model.provider."""
        assert ModelProviderType == Model.__annotations__["provider"]

    def test_model_type_type(self):
        """ModelTypeType should be the annotation for Model.type."""
        assert ModelTypeType == Model.__annotations__["type"]

    def test_model_enabled_type(self):
        """ModelEnabledType should be the annotation for ModelAccess.enabled."""
        assert ModelEnabledType == ModelAccess.__annotations__["enabled"]

    def test_oci_profile_type(self):
        """OCIProfileType should be the annotation for OracleCloudSettings.auth_profile."""
        assert OCIProfileType == OracleCloudSettings.__annotations__["auth_profile"]

    def test_oci_resource_ocid(self):
        """OCIResourceOCID should be the annotation for OracleResource.ocid."""
        assert OCIResourceOCID == OracleResource.__annotations__["ocid"]
