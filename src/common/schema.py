"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ollama hnsw mult ocid testset selectai explainsql showsql vector_search aioptimizer genai

import time
from typing import Optional, Literal, Union, get_args, Any
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from langchain_core.messages import ChatMessage
import oracledb
import common.help_text as help_text

#####################################################
# Literals
#####################################################
DistanceMetrics = Literal["COSINE", "EUCLIDEAN_DISTANCE", "DOT_PRODUCT"]
IndexTypes = Literal["HNSW", "IVF"]

# ModelAPIs
# https://python.langchain.com/api_reference/langchain/chat_models/langchain.chat_models.base.init_chat_model.html
ModelProviders = Literal[
    "openai",
    "anthropic",
    "azure_openai",
    "azure_ai",
    "google_vertexai",
    "google_genai",
    "bedrock",
    "bedrock_converse",
    "cohere",
    "fireworks",
    "together",
    "mistralai",
    "huggingface",
    "groq",
    "ollama",
    "google_anthropic_vertex",
    "deepseek",
    "ibm",
    "nvidia",
    "xai",
    "perplexity",
]


EmbedAPI = Literal[
    "OllamaEmbeddings",
    "OCIGenAIEmbeddings",
    "CompatOpenAIEmbeddings",
    "OpenAIEmbeddings",
    "CohereEmbeddings",
    "HuggingFaceEndpointEmbeddings",
]
LlAPI = Literal[
    "ChatOllama",
    "ChatOCIGenAI",
    "CompatOpenAI",
    "Perplexity",
    "OpenAI",
    "Cohere",
]


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
    model: Optional[str] = Field(default=None, description="Embedding Model")
    chunk_size: Optional[int] = Field(default=0, description="Chunk Size")
    chunk_overlap: Optional[int] = Field(default=0, description="Chunk Overlap")
    distance_metric: Optional[DistanceMetrics] = Field(default=None, description="Distance Metric")
    index_type: Optional[IndexTypes] = Field(default=None, description="Vector Index")


class DatabaseSelectAIObjects(BaseModel):
    """Database SelectAI Objects"""

    owner: Optional[str] = Field(default=None, description="Object Owner", json_schema_extra={"readOnly": True})
    name: Optional[str] = Field(default=None, description="Object Name", json_schema_extra={"readOnly": True})
    enabled: bool = Field(default=False, description="SelectAI Enabled")


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
    selectai: bool = Field(default=False, description="SelectAI Possible")
    selectai_profiles: Optional[list] = Field(
        default=[], description="SelectAI Profiles (read-only)", json_schema_extra={"readOnly": True}
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
# MCP
#####################################################
class MCPModelConfig(BaseModel):
    """MCP Model Configuration"""

    model_id: str = Field(..., description="Model identifier")
    service_type: Literal["ollama", "openai"] = Field(..., description="AI service type")
    base_url: str = Field(default="http://localhost:11434", description="Base URL for API")
    api_key: Optional[str] = Field(default=None, description="API key", json_schema_extra={"sensitive": True})
    enabled: bool = Field(default=True, description="Model availability status")
    streaming: bool = Field(default=False, description="Enable streaming responses")
    temperature: float = Field(default=1.0, description="Model temperature")
    max_tokens: int = Field(default=2048, description="Maximum tokens per response")


class MCPToolConfig(BaseModel):
    """MCP Tool Configuration"""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    parameters: dict[str, Any] = Field(..., description="Tool parameters")
    enabled: bool = Field(default=True, description="Tool availability status")


class MCPSettings(BaseModel):
    """MCP Global Settings"""

    models: list[MCPModelConfig] = Field(default_factory=list, description="Available MCP models")
    tools: list[MCPToolConfig] = Field(default_factory=list, description="Available MCP tools")
    default_model: Optional[str] = Field(default=None, description="Default model identifier")
    enabled: bool = Field(default=True, description="Enable or disable MCP functionality")


#####################################################
# Models
#####################################################
class LanguageModelParameters(BaseModel):
    """Language Model Parameters (also used by settings.py)"""

    context_length: Optional[int] = Field(default=None, description="The context window for Language Model.")
    frequency_penalty: Optional[float] = Field(description=help_text.help_dict["frequency_penalty"], default=0.00)
    max_completion_tokens: Optional[int] = Field(description=help_text.help_dict["max_completion_tokens"], default=256)
    presence_penalty: Optional[float] = Field(description=help_text.help_dict["presence_penalty"], default=0.00)
    temperature: Optional[float] = Field(description=help_text.help_dict["temperature"], default=1.00)
    top_p: Optional[float] = Field(description=help_text.help_dict["top_p"], default=1.00)
    streaming: Optional[bool] = Field(description="Enable Streaming (set by client)", default=False)


class EmbeddingModelParameters(BaseModel):
    """Embedding Model Parameters (also used by settings.py)"""

    max_chunk_size: Optional[int] = Field(default=None, description="Max Chunk Size for Embedding Models.")


class ModelAccess(BaseModel):
    """Patch'able Model Parameters"""

    enabled: Optional[bool] = Field(default=False, description="Model is available for use.")
    url: Optional[str] = Field(default=None, description="URL to Model API.")
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
    type: Literal["ll", "embed", "re-rank"] = Field(..., description="Type of Model.")
    api: str = Field(
        ..., min_length=1, description="API for Model.", examples=["ChatOllama", "OpenAI", "OpenAIEmbeddings"]
    )
    provider: str = Field(..., min_length=1, description="Model Provider", examples=["openai", "anthropic"])
    openai_compat: bool = Field(default=True, description="Is the API OpenAI compatible?")

    @model_validator(mode="after")
    def check_api_matches_type(self):
        """Validate valid API"""
        ll_apis = get_args(LlAPI)
        embed_apis = get_args(EmbedAPI)

        if not self.api or self.api == "unset":
            return self

        if self.type == "ll" and self.api not in ll_apis:
            raise ValueError(f"API '{self.api}' is not valid for type 'll'. Must be one of: {ll_apis}")
        if self.type == "embed" and self.api not in embed_apis:
            raise ValueError(f"API '{self.api}' is not valid for type 'embed'. Must be one of: {embed_apis}")
        return self

    def check_provider_matches_type(self):
        """Validate valid API"""
        providers = get_args(ModelProviders)
        if not self.provider or self.provider == "unset":
            return self

        if self.provider not in providers:
            raise ValueError(f"Provider '{self.provider}' is not valid. Must be one of: {providers}")
        return self


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

    model_config = {
        "extra": "allow"  # enable extra fields
    }


#####################################################
# Prompt Engineering
#####################################################
class PromptText(BaseModel):
    """Patch'able Prompt Parameters"""

    prompt: str = Field(..., min_length=1, description="Prompt Text")


class Prompt(PromptText):
    """Prompt Object"""

    name: str = Field(
        default="Basic Example",
        description="Name of Prompt.",
        examples=["Basic Example", "vector_search Example", "Custom"],
    )
    category: Literal["sys", "ctx"] = Field(..., description="Category of Prompt.")


#####################################################
# Settings
#####################################################
class LargeLanguageSettings(LanguageModelParameters):
    """Store Large Language Settings"""

    model: Optional[str] = Field(default=None, description="Model Name")
    chat_history: bool = Field(default=True, description="Store Chat History")


class PromptSettings(BaseModel):
    """Store Prompt Settings"""

    ctx: str = Field(default="Basic Example", description="Context Prompt Name")
    sys: str = Field(default="Basic Example", description="System Prompt Name")


class VectorSearchSettings(DatabaseVectorStorage):
    """Store vector_search Settings incl VectorStorage"""

    enabled: bool = Field(default=False, description="vector_search Enabled")
    grading: bool = Field(default=True, description="Grade vector_search Results")
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


class SelectAISettings(BaseModel):
    """Store SelectAI Settings"""

    enabled: bool = Field(default=False, description="SelectAI Enabled")
    profile: Optional[str] = Field(default=None, description="SelectAI Profile")
    action: Literal["runsql", "showsql", "explainsql", "narrate"] = Field(
        default="narrate", description="SelectAI Action"
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
    prompts: Optional[PromptSettings] = Field(
        default_factory=PromptSettings, description="Prompt Engineering Settings"
    )
    oci: Optional[OciSettings] = Field(default_factory=OciSettings, description="OCI Settings")
    database: Optional[DatabaseSettings] = Field(default_factory=DatabaseSettings, description="Database Settings")
    vector_search: Optional[VectorSearchSettings] = Field(
        default_factory=VectorSearchSettings, description="Vector Search Settings"
    )
    selectai: Optional[SelectAISettings] = Field(default_factory=SelectAISettings, description="SelectAI Settings")
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
    prompt_configs: Optional[list[Prompt]] = None
    mcp_configs: Optional[list[MCPModelConfig]] = Field(default=None, description="List of MCP configurations")

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

        elif isinstance(obj, list):
            return [cls.recursive_dump_excluding_marked(item, incl_sensitive, incl_readonly) for item in obj]

        elif isinstance(obj, dict):
            return {k: cls.recursive_dump_excluding_marked(v, incl_sensitive, incl_readonly) for k, v in obj.items()}

        else:
            return obj


#####################################################
# Completions
#####################################################
class ChatLogprobs(BaseModel):
    """Log probability information for the choice."""

    content: Optional[dict[str, Union[str, int, dict]]] = Field(
        default=None, description="A list of message content tokens with log probability information."
    )
    refusal: Optional[dict[str, Union[str, int, dict]]] = Field(
        default=None, description="A list of message refusal tokens with log probability information."
    )


class ChatChoices(BaseModel):
    """A list of chat completion choices."""

    index: int = Field(description="The index of the choice in the list of choices.")
    message: ChatMessage = Field(description="A chat completion message generated by the model.")
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls"] = Field(
        description=(
            "The reason the model stopped generating tokens. "
            "This will be stop if the model hit a natural stop point or a provided stop sequence, "
            "length if the maximum number of tokens specified in the request was reached, "
            "content_filter if content was omitted due to a flag from our content filters, "
            "tool_calls if the model called a tool."
        )
    )
    logprobs: Optional[ChatLogprobs] = Field(default=None, description="Log probability information for the choice.")


class ChatUsage(BaseModel):
    """Usage statistics for the completion request."""

    prompt_tokens: int = Field(description="Number of tokens in the prompt.")
    completion_tokens: int = Field(description="Number of tokens in the generated completion.")
    total_tokens: int = Field(description="Total number of tokens used in the request (prompt + completion).")


class ChatResponse(BaseModel):
    """Represents a chat completion response returned by model, based on the provided input."""

    id: str = Field(description="A unique identifier for the chat completion.")
    choices: list[ChatChoices] = Field(description="A list of chat completion choices.")
    created: int = Field(description="The Unix timestamp (in seconds) of when the chat completion was created.")
    model: str = Field(description="The model used for the chat completion.")
    object: str = Field(default="chat.completion", description="The model used for the chat completion.")
    usage: Optional[ChatUsage] = Field(default=None, description="Usage statistics for the completion request.")


class ChatRequest(LanguageModelParameters):
    """
    Request Body (inherits LanguageModelParameters)
    Do not change as this has to remain OpenAI Compatible
    """

    model: Optional[str] = Field(default=None, description="The model to use for chat completions.")
    messages: list[ChatMessage] = Field(description="A list of messages comprising the conversation so far.")

    ### Example Request (will display in docs)
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Hello, how are you?"}],
                    "response_format": {"type": "text"},
                    "temperature": 1,
                    "max_completion_tokens": 10000,
                    "top_p": 1,
                    "frequency_penalty": 0,
                    "presence_penalty": 0,
                }
            ]
        }
    }


#####################################################
# Testbed
#####################################################
class TestSets(BaseModel):
    """TestSets"""

    tid: str = Field(description="Test ID")
    name: str = Field(description="Name of TestSet")
    created: str = Field(description="Date TestSet Loaded")


class TestSetQA(BaseModel):
    """TestSet Q&A"""

    qa_data: list = Field(description="TestSet Q&A Data")


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
ModelTypeType = Model.__annotations__["type"]
ModelEnabledType = ModelAccess.__annotations__["enabled"]
OCIProfileType = OracleCloudSettings.__annotations__["auth_profile"]
OCIResourceOCID = OracleResource.__annotations__["ocid"]
PromptNameType = Prompt.__annotations__["name"]
PromptCategoryType = Prompt.__annotations__["category"]
PromptPromptType = PromptText.__annotations__["prompt"]
SelectAIProfileType = Database.__annotations__["selectai_profiles"]
TestSetsIdType = TestSets.__annotations__["tid"]
TestSetsNameType = TestSets.__annotations__["name"]
TestSetDateType = TestSets.__annotations__["created"]
MCPModelIdType = MCPModelConfig.__annotations__["model_id"]
MCPServiceType = MCPModelConfig.__annotations__["service_type"]
MCPToolNameType = MCPToolConfig.__annotations__["name"]
