"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore hnsw ocid aioptimizer explainsql genai mult ollama showsql rerank

import time
from typing import Optional, Literal, List, Any
from pydantic import BaseModel, Field, PrivateAttr, ConfigDict

from langchain_core.messages import ChatMessage
import oracledb
from common import help_text

#####################################################
# Literals
#####################################################
DistanceMetrics = Literal["COSINE", "EUCLIDEAN_DISTANCE", "DOT_PRODUCT"]
IndexTypes = Literal["HNSW", "IVF"]


#####################################################
# Database
#####################################################
class DatabaseVectorStorage(BaseModel):
    """Database Vector Storage Tables"""

    vector_store: Optional[str] = Field(
        default=None,
        description="Vector Store Table Name (auto-generated, do not set)",
        json_schema_extra={"readOnly": True},
    )
    alias: Optional[str] = Field(default=None, description="Identifiable Alias")
    description: Optional[str] = Field(default=None, description="Human-readable description of table contents")
    model: Optional[str] = Field(default=None, description="Embedding Model")
    chunk_size: Optional[int] = Field(default=0, description="Chunk Size")
    chunk_overlap: Optional[int] = Field(default=0, description="Chunk Overlap")
    distance_metric: Optional[DistanceMetrics] = Field(default=None, description="Distance Metric")
    index_type: Optional[IndexTypes] = Field(default=None, description="Vector Index")


class VectorStoreRefreshRequest(BaseModel):
    """Request for refreshing vector store from OCI bucket"""

    vector_store_alias: str = Field(..., description="Alias of the existing vector store to refresh")
    bucket_name: str = Field(..., description="OCI bucket name containing documents")
    auth_profile: Optional[str] = Field(default="DEFAULT", description="OCI auth profile to use")
    rate_limit: Optional[int] = Field(default=0, description="Rate limit in requests per minute")


class VectorStoreRefreshStatus(BaseModel):
    """Status response for vector store refresh operation"""

    status: Literal["processing", "completed", "failed"] = Field(..., description="Current status")
    message: str = Field(..., description="Status message")
    processed_files: int = Field(default=0, description="Number of files processed")
    new_files: int = Field(default=0, description="Number of new files found")
    updated_files: int = Field(default=0, description="Number of updated files found")
    total_chunks: int = Field(default=0, description="Total number of chunks processed")
    total_chunks_in_store: int = Field(default=0, description="Total number of chunks in vector store after refresh")
    errors: Optional[list[str]] = Field(default=[], description="Any errors encountered")


class DatabaseAuth(BaseModel):
    """Patch'able Database Configuration (sent to oracledb)"""

    user: Optional[str] = Field(default=None, description="Username")
    password: Optional[str] = Field(default=None, description="Password", json_schema_extra={"sensitive": True})
    dsn: Optional[str] = Field(default=None, description="Connect String")
    wallet_password: Optional[str] = Field(
        default=None, description="Wallet Password (for mTLS)", json_schema_extra={"sensitive": True}
    )
    wallet_location: Optional[str] = Field(default=None, description="Wallet Location (for mTLS)")
    config_dir: str = Field(default="tns_admin", description="Location of TNS_ADMIN directory")
    tcp_connect_timeout: int = Field(default=5, description="TCP Timeout in seconds")


class Database(DatabaseAuth):
    """Database Object"""

    name: str = Field(default="DEFAULT", description="Name of Database (Alias)")
    connected: bool = Field(default=False, description="Connection Established", json_schema_extra={"readOnly": True})
    vector_stores: Optional[list[DatabaseVectorStorage]] = Field(
        default=[], description="Vector Storage (read-only)", json_schema_extra={"readOnly": True}
    )
    # Do not expose the connection to the endpoint
    _connection: oracledb.Connection = PrivateAttr(default=None)

    @property
    def connection(self) -> Optional[oracledb.Connection]:
        """Connection String"""
        return self._connection

    def set_connection(self, connection: oracledb.Connection) -> None:
        """Connection String"""
        self._connection = connection


#####################################################
# Models
#####################################################
class LanguageModelParameters(BaseModel):
    """Language Model Parameters (also used by settings.py)"""

    max_input_tokens: Optional[int] = Field(default=None, description="The context window for Language Model.")
    frequency_penalty: Optional[float] = Field(description=help_text.help_dict["frequency_penalty"], default=0.00)
    max_tokens: Optional[int] = Field(description=help_text.help_dict["max_tokens"], default=4096)
    presence_penalty: Optional[float] = Field(description=help_text.help_dict["presence_penalty"], default=0.00)
    temperature: Optional[float] = Field(description=help_text.help_dict["temperature"], default=0.50)
    top_p: Optional[float] = Field(description=help_text.help_dict["top_p"], default=1.00)


class EmbeddingModelParameters(BaseModel):
    """Embedding Model Parameters (also used by settings.py)"""

    max_chunk_size: Optional[int] = Field(default=8192, description="Max Chunk Size for Embedding Models.")


class ModelAccess(BaseModel):
    """Patch'able Model Parameters"""

    enabled: Optional[bool] = Field(default=False, description="Model is available for use.")
    api_base: Optional[str] = Field(default=None, description="Model API Base URL.")
    api_key: Optional[str] = Field(default=None, description="Model API Key.", json_schema_extra={"sensitive": True})


class Model(ModelAccess, LanguageModelParameters, EmbeddingModelParameters):
    """Model Object"""

    id: str = Field(..., min_length=1, description="The model to use")
    object: Literal["model"] = Field(
        default="model",
        description='The object type, always `"model"`. (OpenAI Compatible Only)',
    )
    created: int = Field(
        default_factory=lambda: int(time.time()),
        description="The Unix timestamp (in seconds) when the model was created.",
    )
    owned_by: Literal["aioptimizer"] = Field(
        default="aioptimizer",
        description="OpenAI Compatible Only",
    )
    type: Literal["ll", "embed", "rerank"] = Field(..., description="Type of Model.")
    provider: str = Field(..., min_length=1, description="Model Provider.", examples=["openai", "anthropic", "ollama"])


#####################################################
# Oracle Cloud Infrastructure
#####################################################
class OracleResource(BaseModel):
    """For Oracle Resource OCIDs"""

    ocid: str = Field(..., pattern=r"^([0-9a-zA-Z-_]+[.:])([0-9a-zA-Z-_]*[.:]){3,}([0-9a-zA-Z-_]+)$")


class OracleCloudSettings(BaseModel):
    """Store Oracle Cloud Infrastructure Settings"""

    auth_profile: str = Field(default="DEFAULT", description="Config File Profile")
    namespace: Optional[str] = Field(
        default=None, description="Object Store Namespace", json_schema_extra={"readOnly": True}
    )
    user: Optional[str] = Field(
        default=None,
        description="Optional if using Auth Token",
        pattern=r"^([0-9a-zA-Z-_]+[.:])([0-9a-zA-Z-_]*[.:]){3,}([0-9a-zA-Z-_]+)$",
    )
    security_token_file: Optional[str] = Field(default=None, description="Security Key File for Auth Token")
    authentication: Literal["api_key", "instance_principal", "oke_workload_identity", "security_token"] = Field(
        default="api_key", description="Authentication Method."
    )
    genai_compartment_id: Optional[str] = Field(
        default=None,
        description="Optional Compartment OCID of OCI GenAI services",
        pattern=r"^([0-9a-zA-Z-_]+[.:])([0-9a-zA-Z-_]*[.:]){3,}([0-9a-zA-Z-_]+)$",
    )
    genai_region: Optional[str] = Field(default=None, description="Optional Region OCID of OCI GenAI services")

    model_config = ConfigDict(extra="allow")


#####################################################
# Prompt Engineering (MCP-based)
#####################################################
class MCPPrompt(BaseModel):
    """MCP Prompt metadata and content"""

    name: str = Field(..., description="MCP prompt name (e.g., 'optimizer_basic-default')")
    title: str = Field(..., description="Human-readable title")
    description: str = Field(default="", description="Prompt purpose and usage")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    text: str = Field(..., description="Effective prompt text (override if exists, otherwise default)")


#####################################################
# Settings
#####################################################
class LargeLanguageSettings(LanguageModelParameters):
    """Store Large Language Settings"""

    model: Optional[str] = Field(default=None, description="Model Name")
    chat_history: bool = Field(default=True, description="Store Chat History")


class VectorSearchSettings(DatabaseVectorStorage):
    """Store vector_search Settings"""

    discovery: bool = Field(default=True, description="Auto-discover Vector Stores")
    rephrase: bool = Field(default=True, description="Rephrase User Prompt")
    grade: bool = Field(default=True, description="Grade Vector Search Results")
    search_type: Literal["Similarity", "Similarity Score Threshold", "Maximal Marginal Relevance"] = Field(
        default="Similarity", description="Search Type"
    )
    top_k: Optional[int] = Field(default=4, ge=1, le=10000, description="Top K")
    score_threshold: Optional[float] = Field(
        default=0.0, ge=0.0, le=1.0, description="Minimum Relevance Threshold (for Similarity Score Threshold)"
    )
    fetch_k: Optional[int] = Field(default=20, ge=1, le=10000, description="Fetch K (for Maximal Marginal Relevance)")
    lambda_mult: Optional[float] = Field(
        default=0.5, ge=0.0, le=1.0, description="Degree of Diversity (for Maximal Marginal Relevance)"
    )


class OciSettings(BaseModel):
    """OCI Settings"""

    auth_profile: Optional[str] = Field(default="DEFAULT", description="Oracle Cloud Settings Profile")


class DatabaseSettings(BaseModel):
    """Database Settings"""

    alias: str = Field(default="DEFAULT", description="Name of Database (Alias)")


class TestBedSettings(BaseModel):
    """TestBed Settings"""

    qa_ll_model: Optional[str] = Field(default=None, description="Q&A Language Model Name")
    qa_embed_model: Optional[str] = Field(default=None, description="Q&A Embed Model Name")
    judge_model: Optional[str] = Field(default=None, description="Judge Model Name")


class Settings(BaseModel):
    """Client Settings"""

    client: str = Field(
        ...,
        min_length=1,
        description="Unique Client Identifier",
    )
    ll_model: Optional[LargeLanguageSettings] = Field(
        default_factory=LargeLanguageSettings, description="Large Language Settings"
    )
    oci: Optional[OciSettings] = Field(default_factory=OciSettings, description="OCI Settings")
    database: Optional[DatabaseSettings] = Field(default_factory=DatabaseSettings, description="Database Settings")
    tools_enabled: List[str] = Field(
        default_factory=list,
        description="List of enabled MCP tools for this client (empty means LLM only)",
    )
    vector_search: Optional[VectorSearchSettings] = Field(
        default_factory=VectorSearchSettings, description="Vector Search Settings"
    )
    testbed: Optional[TestBedSettings] = Field(default_factory=TestBedSettings, description="TestBed Settings")


#####################################################
# Full Configuration
#####################################################
class Configuration(BaseModel):
    """Full Configuration (with client settings)"""

    client_settings: Settings
    database_configs: Optional[list[Database]] = None
    model_configs: Optional[list[Model]] = None
    oci_configs: Optional[list[OracleCloudSettings]] = None
    prompt_configs: Optional[list[MCPPrompt]] = None

    def model_dump_public(self, incl_sensitive: bool = False, incl_readonly: bool = False) -> dict:
        """Remove marked fields for FastAPI Response"""
        return self.recursive_dump_excluding_marked(self, incl_sensitive, incl_readonly)

    @classmethod
    def recursive_dump_excluding_marked(cls, obj: Any, incl_sensitive: bool, incl_readonly: bool) -> Any:
        """Recursively include fields, including extras, and exclude marked ones"""
        if isinstance(obj, BaseModel):
            output = {}

            # Get declared fields
            for name, field in obj.__class__.model_fields.items():
                extras = field.json_schema_extra or {}
                is_readonly = extras.get("readOnly", False)
                is_sensitive = extras.get("sensitive", False)
                if (is_readonly and not incl_readonly) or (is_sensitive and not incl_sensitive):
                    continue
                value = getattr(obj, name)
                output[name] = cls.recursive_dump_excluding_marked(value, incl_sensitive, incl_readonly)

            # Handle extra fields
            if obj.__pydantic_extra__:
                for key, value in obj.__pydantic_extra__.items():
                    output[key] = cls.recursive_dump_excluding_marked(value, incl_sensitive, incl_readonly)

            return output

        if isinstance(obj, list):
            return [cls.recursive_dump_excluding_marked(item, incl_sensitive, incl_readonly) for item in obj]

        if isinstance(obj, dict):
            return {k: cls.recursive_dump_excluding_marked(v, incl_sensitive, incl_readonly) for k, v in obj.items()}

        return obj


#####################################################
# Completions
#####################################################
class ChatRequest(LanguageModelParameters):
    """
    Request Body (inherits LanguageModelParameters)
    Do not change as this has to remain OpenAI Compatible
    """

    model: Optional[str] = Field(default=None, description="The model to use for chat completions.")
    messages: list[ChatMessage] = Field(description="A list of messages comprising the conversation so far.")

    ### Example Request (will display in docs)
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Hello, how are you?"}],
                    "response_format": {"type": "text"},
                    "temperature": 1,
                    "max_tokens": 10000,
                    "top_p": 1,
                    "frequency_penalty": 0,
                    "presence_penalty": 0,
                }
            ]
        }
    )


#####################################################
# Testbed
#####################################################
class QASets(BaseModel):
    """QA Sets - Collection of Q&A test sets for testbed evaluation"""

    tid: str = Field(description="Test ID")
    name: str = Field(description="Name of QA Set")
    created: str = Field(description="Date QA Set Loaded")


class QASetData(BaseModel):
    """QA Set Data - Question/Answer pairs for testbed evaluation"""

    qa_data: list = Field(description="QA Set Data")


class Evaluation(BaseModel):
    """Evaluation"""

    eid: str = Field(description="Evaluation ID")
    evaluated: str = Field(description="Date of Evaluation")
    correctness: float = Field(description="Correctness")


class EvaluationReport(Evaluation):
    """Evaluation Report"""

    settings: Settings = Field(description="Settings for Evaluation")
    report: dict = Field(description="Full Report")
    correct_by_topic: dict = Field(description="Correctness by Topic")
    failures: dict = Field(description="Failures")
    html_report: str = Field(description="HTML Report")


#####################################################
# Types
#####################################################
ClientIdType = Settings.__annotations__["client"]
DatabaseNameType = Database.__annotations__["name"]
VectorStoreTableType = DatabaseVectorStorage.__annotations__["vector_store"]
ModelIdType = Model.__annotations__["id"]
ModelProviderType = Model.__annotations__["provider"]
ModelTypeType = Model.__annotations__["type"]
ModelEnabledType = ModelAccess.__annotations__["enabled"]
OCIProfileType = OracleCloudSettings.__annotations__["auth_profile"]
OCIResourceOCID = OracleResource.__annotations__["ocid"]
QASetsIdType = QASets.__annotations__["tid"]
QASetsNameType = QASets.__annotations__["name"]
QASetsDateType = QASets.__annotations__["created"]
