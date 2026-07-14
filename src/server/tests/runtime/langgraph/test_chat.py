"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for LangGraph ChatOrchestrator.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from server.app.api.v1.schemas.chat import SqlMetadata, TokenUsage, VsMetadata
from server.app.database.config import DdsConnectionError
from server.app.mcp.prompts.registry import get_factory_text
from server.app.runtime.common import (
    CLASSIFIER_PROMPT_NAME,
    SYNTHESIS_PROMPT_NAME,
    LLMConfigurationError,
    SessionMetadata,
    validate_classifier_prompt,
    validate_synthesis_template,
)
from server.app.runtime.langgraph.chat import ChatOrchestrator
from server.app.runtime.langgraph.multi_tool import CombinedSession
from server.app.runtime.langgraph.session import (
    AgentGraphSession,
    GraphFlowSession,
    NL2SQLGraphSession,
)
from server.tests.constants import TEST_OLLAMA_MODEL_ID, TEST_OLLAMA_MODEL_KEY
from server.tests.runtime.chat_base import (
    ApiKeyLivenessBase,
    CacheBase,
    ExecuteChatBase,
    StreamBase,
)
from server.tests.runtime.langgraph.helpers import mock_compiled_graph
from server.tests.runtime.shared_helpers import mock_client_settings, temporary_oci_configs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(cs=None, **cs_kwargs):
    """Build a ChatOrchestrator with a mock resolve_client."""
    if cs is None:
        cs = mock_client_settings(**cs_kwargs)
    return ChatOrchestrator(
        server_url="http://127.0.0.1:8000/mcp",
        api_key="test-key",
        resolve_client=lambda _client: cs,
    )


class _LangGraphChatMixin:
    """Provides shared attributes for LangGraph ChatOrchestrator tests."""

    ChatOrchestratorClass = ChatOrchestrator
    LLMConfigurationError = LLMConfigurationError

    @staticmethod
    def make_orchestrator(**kwargs):
        """Create a LangGraph ChatOrchestrator for testing."""
        return _make_orchestrator(**kwargs)


# ---------------------------------------------------------------------------
# TestChatOrchestratorCache
# ---------------------------------------------------------------------------


class TestChatOrchestratorCache(_LangGraphChatMixin, CacheBase):
    """Tests for session caching and invalidation."""

    @pytest.mark.anyio
    async def test_session_cached_on_second_call(self):
        """Verify second call reuses cached session."""
        orch = _make_orchestrator()
        mock_session = MagicMock(spec=AgentGraphSession)
        mock_session.chat = AsyncMock(return_value="cached")
        mock_session.last_metadata = SessionMetadata()

        build_mock = AsyncMock(return_value=mock_session)

        with patch.object(orch, "_build_session", build_mock):
            await orch.execute_chat("q1", "c1")
            await orch.execute_chat("q2", "c1")

        assert build_mock.await_count == 1

    @pytest.mark.anyio
    async def test_session_rebuilt_when_oci_compartment_changes(self):
        """Cache must invalidate when the resolved OCI profile's compartment changes.

        The OCI auth kwargs (oci_compartment_id, oci_region, oci_signer) are
        baked into the OracleChatLiteLLM at session-build time. If the profile
        is updated after a session is cached, subsequent calls reuse the stale
        graph and litellm raises ``kwarg oci_compartment_id is required``. The
        cache identity therefore needs to fold in OCI profile state so a
        compartment change forces a rebuild.
        """
        from server.app.oci.schemas import OciProfileConfig

        profile = OciProfileConfig(auth_profile="DEFAULT")
        with temporary_oci_configs([profile], client_auth_profile="DEFAULT"):
            cs = mock_client_settings(provider="oci", model_id="xai.grok-4.3")
            orch = ChatOrchestrator(
                server_url="http://127.0.0.1:8000/mcp",
                api_key="test-key",
                resolve_client=lambda _c: cs,
            )

            mock_session = MagicMock(spec=AgentGraphSession)
            mock_session.chat = AsyncMock(return_value="ok")
            mock_session.last_metadata = SessionMetadata()
            build_mock = AsyncMock(return_value=mock_session)

            with patch.object(orch, "_build_session", build_mock):
                # First call: profile has no compartment yet (mirrors the GUI
                # sequence where chat builds a session before OCI is configured).
                await orch.execute_chat("q1", "c1")
                profile.genai_compartment_id = "ocid1.compartment.oc1..real"
                profile.genai_region = "us-chicago-1"
                await orch.execute_chat("q2", "c1")

            assert build_mock.await_count == 2, (
                "Expected session rebuild after genai_compartment_id changed, "
                f"but _build_session was called {build_mock.await_count} time(s). "
                "Cache identity is OCI-blind — stale graph keeps None compartment."
            )

    @pytest.mark.anyio
    async def test_session_rebuilt_when_oci_api_key_fields_change(self):
        """Cache must invalidate when API-key auth fields rotate.

        ``build_oci_litellm_params`` bakes ``oci_tenancy / oci_user /
        oci_fingerprint / oci_key_file`` into the LLM's ``model_kwargs`` for
        api_key profiles. Rotating any of those — e.g. swapping the user
        OCID or pointing key_file at a new PEM — must force a rebuild so
        the new credentials reach LiteLLM. ``authentication`` itself
        decides whether the loader emits a signer or those four fields,
        so a switch between modes must also invalidate.
        """
        from server.app.oci.schemas import OciProfileConfig

        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            authentication="api_key",
            tenancy="ocid1.tenancy.oc1..old",
            user="ocid1.user.oc1..old",
            fingerprint="aa:bb:cc",
            key_file="/path/old.pem",
            genai_compartment_id="ocid1.compartment.oc1..c",
            genai_region="us-chicago-1",
        )
        with temporary_oci_configs([profile], client_auth_profile="DEFAULT"):
            cs = mock_client_settings(provider="oci", model_id="xai.grok-4.3")
            orch = ChatOrchestrator(
                server_url="http://127.0.0.1:8000/mcp",
                api_key="test-key",
                resolve_client=lambda _c: cs,
            )

            mock_session = MagicMock(spec=AgentGraphSession)
            mock_session.chat = AsyncMock(return_value="ok")
            mock_session.last_metadata = SessionMetadata()
            build_mock = AsyncMock(return_value=mock_session)

            with patch.object(orch, "_build_session", build_mock):
                await orch.execute_chat("q1", "c1")
                profile.user = "ocid1.user.oc1..rotated"
                await orch.execute_chat("q2", "c1")

            assert build_mock.await_count == 2, (
                "Expected rebuild when api_key fields rotate, but "
                f"_build_session was called {build_mock.await_count} time(s). "
                "Identity must cover every field build_oci_litellm_params consumes."
            )

    @pytest.mark.anyio
    async def test_oci_identity_resolves_clients_own_auth_profile(self):
        """Identity must follow the cached client's ``oci.auth_profile``,
        not the global CONFIGURED selection.

        A chat client (e.g. the SERVER client after ``/settings/server/copy``,
        or a long-lived per-tab session) can be pinned to a different OCI
        profile than CONFIGURED. Rotating *that* profile must invalidate
        its cached graph; otherwise the cache hands back a session built
        with stale auth params for the wrong profile.
        """
        from server.app.core.schemas import ClientSettings
        from server.app.oci.schemas import OciProfileConfig

        profile_a = OciProfileConfig(
            auth_profile="PROFILE_A",
            genai_compartment_id="ocid1.compartment.oc1..a",
            genai_region="us-chicago-1",
        )
        profile_b = OciProfileConfig(
            auth_profile="PROFILE_B",
            genai_compartment_id="ocid1.compartment.oc1..b-old",
            genai_region="us-chicago-1",
        )
        # CONFIGURED stays on A; the chat client pins itself to B.
        with temporary_oci_configs([profile_a, profile_b], client_auth_profile="PROFILE_A"):
            cs = ClientSettings(client="c1")
            cs.ll_model.provider = "oci"
            cs.ll_model.id = "xai.grok-4.3"
            cs.oci.auth_profile = "PROFILE_B"

            orch = ChatOrchestrator(
                server_url="http://127.0.0.1:8000/mcp",
                api_key="test-key",
                resolve_client=lambda _c: cs,
            )

            mock_session = MagicMock(spec=AgentGraphSession)
            mock_session.chat = AsyncMock(return_value="ok")
            mock_session.last_metadata = SessionMetadata()
            build_mock = AsyncMock(return_value=mock_session)

            with patch.object(orch, "_build_session", build_mock):
                await orch.execute_chat("q1", "c1")
                profile_b.genai_compartment_id = "ocid1.compartment.oc1..b-new"
                await orch.execute_chat("q2", "c1")

            assert build_mock.await_count == 2, (
                "Identity resolves CONFIGURED's profile, so mutating the "
                "client-pinned profile does not invalidate the cache. "
                f"_build_session was called {build_mock.await_count} time(s)."
            )

    @pytest.mark.anyio
    async def test_refresh_prompts_recomputes_identity_after_oci_change(self):
        """After refresh_prompts rebuilds with current OCI state, the cached
        identity must reflect that current state — not the pre-refresh one.

        Otherwise the freshly-built graph (with new model_kwargs) is filed
        under the old identity: the next chat sees an identity mismatch
        and rebuilds unnecessarily, and worse, if the profile reverts to
        its prior values the cache hands back a session that was built
        for different params as if it matched.
        """
        from server.app.oci.schemas import OciProfileConfig

        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            genai_compartment_id="ocid1.compartment.oc1..A",
            genai_region="us-chicago-1",
        )
        with temporary_oci_configs([profile], client_auth_profile="DEFAULT"):
            cs = mock_client_settings(provider="oci", model_id="xai.grok-4.3")
            orch = ChatOrchestrator(
                server_url="http://127.0.0.1:8000/mcp",
                api_key="test-key",
                resolve_client=lambda _c: cs,
            )
            built = _make_agent_session()
            with patch.object(orch, "_build_session", AsyncMock(return_value=built)):
                await orch.execute_chat("q", "c1")

            profile.genai_compartment_id = "ocid1.compartment.oc1..B"
            rebuilt = _make_agent_session()
            with patch.object(orch, "_build_agent_session", AsyncMock(return_value=rebuilt)):
                await orch.refresh_prompts()

            stored_identity = orch._session_cache[("c1", "llm_only")][2]
            stored_compartment = stored_identity.get("_oci_resolved", {}).get(
                "genai_compartment_id"
            )
            assert stored_compartment == "ocid1.compartment.oc1..B", (
                "After refresh_prompts the cached identity should describe the "
                "session that was actually rebuilt (current OCI state), "
                f"but it still records {stored_compartment!r}."
            )


# ---------------------------------------------------------------------------
# TestExecuteChat
# ---------------------------------------------------------------------------


class TestExecuteChat(_LangGraphChatMixin, ExecuteChatBase):
    """Tests for ChatOrchestrator.execute_chat."""

    def _mock_llm_session(self):
        """Create a mock LLM session."""
        session = MagicMock(spec=AgentGraphSession)
        session.chat = AsyncMock(return_value="hello back")
        session.last_metadata = SessionMetadata()
        return session

    @pytest.mark.anyio
    async def test_returns_token_usage(self):
        """Verify execute_chat returns token_usage from session."""
        orch = _make_orchestrator()
        mock_session = MagicMock(spec=AgentGraphSession)
        mock_session.chat = AsyncMock(return_value="answer")
        mock_session.last_metadata = SessionMetadata(
            token_usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("test", "c1")

        assert result["token_usage"] == TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)

    @pytest.mark.anyio
    async def test_nl2sql_route(self):
        """Verify NL2SQL route calls AgentGraphSession.chat (LangGraph uses agent)."""
        orch = _make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = MagicMock(spec=AgentGraphSession)
        mock_session.chat = AsyncMock(return_value="sql result")
        mock_session.last_metadata = SessionMetadata()

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("show tables", "test_client")

        assert result["result"] == "sql result"
        assert result["route"] == "nl2sql"

    @pytest.mark.anyio
    async def test_nl2sql_route_returns_sql_metadata(self):
        """NL2SQL responses should carry executed SQL metadata."""
        orch = _make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = MagicMock(spec=AgentGraphSession)
        mock_session.chat = AsyncMock(return_value="sql result")
        mock_session.last_metadata = SessionMetadata(
            sql_metadata=SqlMetadata(executed_sql=["SELECT * FROM drivers"]),
        )

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("show drivers", "test_client")

        assert result["sql_metadata"] == SqlMetadata(executed_sql=["SELECT * FROM drivers"])

    @pytest.mark.anyio
    async def test_vecsearch_route(self):
        """Verify VecSearch route calls GraphFlowSession.execute."""
        orch = _make_orchestrator(tools_enabled=["Vector Search"])
        mock_session = MagicMock(spec=GraphFlowSession)
        mock_session.execute = AsyncMock(return_value="doc result")
        mock_session.last_metadata = SessionMetadata(
            vs_metadata=VsMetadata(documents=[{"source": "doc1"}]),
        )

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("what is X?", "test_client")

        assert result["result"] == "doc result"
        assert result["route"] == "vecsearch"
        assert result["vs_metadata"] == VsMetadata(documents=[{"source": "doc1"}])


# ---------------------------------------------------------------------------
# TestExecuteChatStream
# ---------------------------------------------------------------------------


class TestExecuteChatStream(_LangGraphChatMixin, StreamBase):
    """Tests for ChatOrchestrator.execute_chat_stream."""

    def _mock_agent_session(self):
        """Create a mock agent session."""
        session = MagicMock(spec=AgentGraphSession)
        session.last_metadata = SessionMetadata()
        return session

    def _mock_combined_session(self):
        """Create a mock combined session."""
        session = MagicMock(spec=CombinedSession)
        session.last_metadata = SessionMetadata()
        return session

    def _mock_cached_stream_session(self):
        """Create a mock cached stream session."""
        session = MagicMock(spec=AgentGraphSession)
        session.chat = AsyncMock(return_value="answer")
        session.last_metadata = SessionMetadata()
        return session

    def _mock_vs_metadata_session(self):
        """Create a mock vs metadata session."""
        session = MagicMock(spec=GraphFlowSession)
        session.execute = AsyncMock(return_value="answer")
        session.last_metadata = SessionMetadata(
            vs_metadata=VsMetadata(documents=[{"searched_tables": ["t1"]}]),
        )
        session.graph = MagicMock()
        session.graph.nodes = {}
        return session


# ---------------------------------------------------------------------------
# TestApiKeyLiveness
# ---------------------------------------------------------------------------


class TestApiKeyLiveness(_LangGraphChatMixin, ApiKeyLivenessBase):
    """Verify the orchestrator uses the *current* API key."""


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _make_agent_session():
    """Build a real AgentGraphSession with a mock graph."""
    return AgentGraphSession(mock_compiled_graph())


def _make_nl2sql_session(cs=None, thread_id=""):
    """Build a real NL2SQLGraphSession with a mock graph."""
    if cs is None:
        from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ

        cs = SAMPLE_CLIENT_SETTINGS_OBJ
    return NL2SQLGraphSession(MagicMock(), cs, thread_id=thread_id)


def _make_combined_session(nl2sql_session=None):
    """Build a CombinedSession with mock sub-sessions."""
    vs = MagicMock(spec=GraphFlowSession)
    if nl2sql_session is None:
        nl2sql_session = _make_nl2sql_session(thread_id="c1")
    return CombinedSession(
        vs,
        nl2sql_session,
        TEST_OLLAMA_MODEL_KEY,
        "system prompt",
    )


# ---------------------------------------------------------------------------
# TestCombinedPromptFetch
# ---------------------------------------------------------------------------


class TestCombinedPromptFetch:
    """Verify the combined-session classifier + synthesis prompts come from MCP
    and fall back to the built-in default when structural validation fails."""

    def test_validate_classifier_prompt_requires_all_tokens(self):
        assert validate_classifier_prompt("nl2sql vecsearch both {{query}}")
        assert not validate_classifier_prompt("vecsearch both {{query}}")
        assert not validate_classifier_prompt("nl2sql both {{query}}")
        assert not validate_classifier_prompt("nl2sql vecsearch {{query}}")
        assert not validate_classifier_prompt("nl2sql vecsearch both")

    def test_validate_synthesis_template_requires_all_slots(self):
        good = "{system_prompt} {query} {sql_answer} {search_answer}"
        assert validate_synthesis_template(good)
        assert not validate_synthesis_template("{query} {sql_answer} {search_answer}")
        assert not validate_synthesis_template("{system_prompt} {sql_answer} {search_answer}")
        assert not validate_synthesis_template("{system_prompt} {query} {search_answer}")
        assert not validate_synthesis_template("{system_prompt} {query} {sql_answer}")

    def test_validate_synthesis_template_rejects_unformattable(self):
        """A template that passes the substring check but raises at
        ``.format()`` time would crash combined synthesis (the call is
        outside the synthesize() try-block). Validator must reject."""
        all_slots = "{system_prompt} {query} {sql_answer} {search_answer}"
        # Stray extra placeholder — KeyError at format time.
        assert not validate_synthesis_template(all_slots + " {extra_field}")
        # Positional placeholder — IndexError when only kwargs are bound.
        assert not validate_synthesis_template(all_slots + " {0}")
        # Unclosed brace — ValueError at format time.
        assert not validate_synthesis_template(all_slots + " {unclosed")
        # Escaped braces are fine — they render as literal text.
        assert validate_synthesis_template(all_slots + " {{escaped}}")

    def test_factory_prompts_pass_their_validators(self):
        """Sanity check: the canonical factory entries in
        ``mcp/prompts/defaults.py`` must themselves validate. If this fails,
        the fallback chain has no safe landing — both fetched-text-bad and
        factory-bad would crash combined synthesis."""
        classifier = get_factory_text(CLASSIFIER_PROMPT_NAME)
        synthesis = get_factory_text(SYNTHESIS_PROMPT_NAME)
        assert classifier is not None and validate_classifier_prompt(classifier)
        assert synthesis is not None and validate_synthesis_template(synthesis)

    @pytest.mark.anyio
    async def test_invalid_classifier_prompt_falls_back_with_warning(self):
        """A fetched classifier prompt missing a decision token must not be
        used — the response parser would silently default to BOTH on every
        turn. Fall back to the factory entry and warn."""
        orch = _make_orchestrator(tools_enabled=["NL2SQL", "Vector Search"])

        async def fake_fetch(_server_url, _api_key, prompt_name):
            if prompt_name == CLASSIFIER_PROMPT_NAME:
                return "broken prompt with only nl2sql token and {{query}}"
            return get_factory_text(prompt_name) or ""

        graph = mock_compiled_graph()
        with (
            patch("server.app.runtime.common.fetch_prompt_with_fallback", side_effect=fake_fetch),
            patch("server.app.runtime.langgraph.chat.fetch_prompt_with_fallback", side_effect=fake_fetch),
            patch("server.app.runtime.langgraph.chat.build_vecsearch_graph", AsyncMock(return_value=graph)),
            patch("server.app.runtime.langgraph.chat.build_nl2sql_graph", AsyncMock(return_value=graph)),
            patch("server.app.runtime.langgraph.chat.find_model", return_value=None),
            patch("server.app.runtime.langgraph.chat.LOGGER") as mock_logger,
        ):
            session = await orch._build_combined_session(
                mock_client_settings(tools_enabled=["NL2SQL", "Vector Search"])
            )

        assert session._classifier_prompt == get_factory_text(CLASSIFIER_PROMPT_NAME)
        assert any(
            CLASSIFIER_PROMPT_NAME in str(c) and "validation" in str(c)
            for c in mock_logger.warning.call_args_list
        )

    @pytest.mark.anyio
    async def test_invalid_synthesis_template_falls_back_with_warning(self):
        """A synthesis template missing a format slot would silently drop
        half the input. Fall back to the factory entry and warn."""
        orch = _make_orchestrator(tools_enabled=["NL2SQL", "Vector Search"])

        async def fake_fetch(_server_url, _api_key, prompt_name):
            if prompt_name == SYNTHESIS_PROMPT_NAME:
                return "Only {query} no other slots"
            return get_factory_text(prompt_name) or ""

        graph = mock_compiled_graph()
        with (
            patch("server.app.runtime.common.fetch_prompt_with_fallback", side_effect=fake_fetch),
            patch("server.app.runtime.langgraph.chat.fetch_prompt_with_fallback", side_effect=fake_fetch),
            patch("server.app.runtime.langgraph.chat.build_vecsearch_graph", AsyncMock(return_value=graph)),
            patch("server.app.runtime.langgraph.chat.build_nl2sql_graph", AsyncMock(return_value=graph)),
            patch("server.app.runtime.langgraph.chat.find_model", return_value=None),
            patch("server.app.runtime.langgraph.chat.LOGGER") as mock_logger,
        ):
            session = await orch._build_combined_session(
                mock_client_settings(tools_enabled=["NL2SQL", "Vector Search"])
            )

        assert session._synthesis_template == get_factory_text(SYNTHESIS_PROMPT_NAME)
        assert any(
            SYNTHESIS_PROMPT_NAME in str(c) and "validation" in str(c)
            for c in mock_logger.warning.call_args_list
        )

    @pytest.mark.anyio
    async def test_valid_prompts_are_passed_through(self):
        """A valid fetched prompt overrides the factory text and reaches the session."""
        orch = _make_orchestrator(tools_enabled=["NL2SQL", "Vector Search"])
        custom_classifier = "Pick nl2sql vecsearch or both. Query: {{query}}"
        custom_synthesis = "Sys: {system_prompt}\nQ: {query}\nSQL: {sql_answer}\nVS: {search_answer}"

        async def fake_fetch(_server_url, _api_key, prompt_name):
            return {
                CLASSIFIER_PROMPT_NAME: custom_classifier,
                SYNTHESIS_PROMPT_NAME: custom_synthesis,
            }.get(prompt_name, get_factory_text(prompt_name) or "")

        graph = mock_compiled_graph()
        with (
            patch("server.app.runtime.common.fetch_prompt_with_fallback", side_effect=fake_fetch),
            patch("server.app.runtime.langgraph.chat.fetch_prompt_with_fallback", side_effect=fake_fetch),
            patch("server.app.runtime.langgraph.chat.build_vecsearch_graph", AsyncMock(return_value=graph)),
            patch("server.app.runtime.langgraph.chat.build_nl2sql_graph", AsyncMock(return_value=graph)),
            patch("server.app.runtime.langgraph.chat.find_model", return_value=None),
        ):
            session = await orch._build_combined_session(
                mock_client_settings(tools_enabled=["NL2SQL", "Vector Search"])
            )

        assert session._classifier_prompt == custom_classifier
        assert session._synthesis_template == custom_synthesis


# ---------------------------------------------------------------------------
# TestCombinedSessionOciAuth
# ---------------------------------------------------------------------------


class TestCombinedSessionOciAuth:
    """Verify _build_combined_session resolves OCI auth params for classify/synthesize.

    The combined session's classify/synthesize calls go through OracleChatLiteLLM
    directly (not through LiteLlmModelSpec), so OCI auth must be plumbed in by
    the builder. Without this, LiteLLM raises ``Missing required parameters:
    oci_user, oci_fingerprint, oci_tenancy, oci_compartment_id`` at synthesis
    time and combined falls back to concatenated answers.
    """

    @pytest.mark.anyio
    async def test_build_combined_session_forwards_oci_auth_params(self):
        from server.app.core.schemas import ClientSettings
        from server.app.oci.schemas import OciProfileConfig

        profile = OciProfileConfig(
            auth_profile="DEFAULT",
            authentication="api_key",
            tenancy="ocid1.tenancy.oc1..t",
            user="ocid1.user.oc1..u",
            fingerprint="aa:bb:cc",
            key_file="/etc/oci/key.pem",
            genai_compartment_id="ocid1.compartment.oc1..c",
            genai_region="us-chicago-1",
        )
        with temporary_oci_configs([profile], client_auth_profile="DEFAULT"):
            cs = ClientSettings(client="c1")
            cs.ll_model.provider = "oci"
            cs.ll_model.id = "openai.gpt-oss-120b"

            orch = ChatOrchestrator(
                server_url="http://127.0.0.1:8000/mcp",
                api_key="test-key",
                resolve_client=lambda _c: cs,
            )

            with patch(
                "server.app.runtime.langgraph.chat.build_vecsearch_graph",
                new=AsyncMock(return_value=mock_compiled_graph()),
            ), patch(
                "server.app.runtime.langgraph.chat.build_nl2sql_graph",
                new=AsyncMock(return_value=mock_compiled_graph()),
            ), patch(
                "server.app.runtime.langgraph.chat.fetch_prompt_for_route",
                new=AsyncMock(return_value=""),
            ), patch(
                "server.app.runtime.langgraph.chat.fetch_prompt_with_fallback",
                new=AsyncMock(side_effect=lambda _u, _k, name: get_factory_text(name) or ""),
            ), patch(
                "server.app.runtime.langgraph.chat.find_model",
                return_value=None,
            ), patch("server.app.runtime.langgraph.chat.CombinedSession") as mock_combined_cls:
                mock_combined_cls.return_value = MagicMock(spec=CombinedSession)
                await orch._build_combined_session(cs, client="c1")

            mk = mock_combined_cls.call_args.kwargs.get("model_kwargs")
            assert mk, "OCI provider must pass model_kwargs to CombinedSession"
            assert mk["oci_user"] == "ocid1.user.oc1..u"
            assert mk["oci_tenancy"] == "ocid1.tenancy.oc1..t"
            assert mk["oci_fingerprint"] == "aa:bb:cc"
            assert mk["oci_key_file"] == "/etc/oci/key.pem"
            assert mk["oci_compartment_id"] == "ocid1.compartment.oc1..c"
            assert mk["oci_region"] == "us-chicago-1"

    @pytest.mark.anyio
    async def test_build_combined_session_skips_oci_kwargs_for_non_oci_provider(self):
        """Non-OCI providers must not receive OCI model_kwargs (would leak auth into Ollama/OpenAI requests)."""
        cs = mock_client_settings(provider="ollama", model_id=TEST_OLLAMA_MODEL_ID)
        orch = _make_orchestrator(cs=cs)

        with patch(
            "server.app.runtime.langgraph.chat.build_vecsearch_graph",
            new=AsyncMock(return_value=mock_compiled_graph()),
        ), patch(
            "server.app.runtime.langgraph.chat.build_nl2sql_graph",
            new=AsyncMock(return_value=mock_compiled_graph()),
        ), patch(
            "server.app.runtime.langgraph.chat.fetch_prompt_for_route",
            new=AsyncMock(return_value=""),
        ), patch(
            "server.app.runtime.langgraph.chat.fetch_prompt_with_fallback",
            new=AsyncMock(side_effect=lambda _u, _k, name: get_factory_text(name) or ""),
        ), patch(
            "server.app.runtime.langgraph.chat.find_model",
            return_value=None,
        ), patch("server.app.runtime.langgraph.chat.CombinedSession") as mock_combined_cls:
            mock_combined_cls.return_value = MagicMock(spec=CombinedSession)
            await orch._build_combined_session(cs, client="c1")

        assert not mock_combined_cls.call_args.kwargs.get("model_kwargs")


# ---------------------------------------------------------------------------
# TestHistoryFeed
# ---------------------------------------------------------------------------


class TestHistoryFeed:
    """Sessions are stateless w.r.t. history; the orchestrator feeds it in."""

    @pytest.mark.anyio
    async def test_agent_session_receives_history_messages_from_store(self):
        from langchain_core.messages import AIMessage, HumanMessage

        cs = mock_client_settings(chat_history=True)
        orch = _make_orchestrator(cs=cs)
        orch.history.append("c1", "user", "I am Driver 1.")
        orch.history.append("c1", "assistant", "Acknowledged.")

        mock_session = MagicMock(spec=AgentGraphSession)
        mock_session.chat = AsyncMock(return_value="team apex")
        mock_session.last_metadata = SessionMetadata()

        with patch.object(orch, "_build_session", AsyncMock(return_value=mock_session)):
            await orch.execute_chat("Which team?", "c1")

        passed = mock_session.chat.call_args.kwargs["history_messages"]
        assert isinstance(passed[0], HumanMessage)
        assert isinstance(passed[1], AIMessage)
        assert [m.content for m in passed] == ["I am Driver 1.", "Acknowledged."]

    @pytest.mark.anyio
    async def test_flow_session_receives_history_text_from_store(self):
        cs = mock_client_settings(chat_history=True, tools_enabled=["Vector Search"])
        orch = _make_orchestrator(cs=cs)
        orch.history.append("c1", "user", "what is X?")
        orch.history.append("c1", "assistant", "X is foo.")

        mock_session = MagicMock(spec=GraphFlowSession)
        mock_session.execute = AsyncMock(return_value="answer")
        mock_session.last_metadata = SessionMetadata()

        with patch.object(orch, "_build_session", AsyncMock(return_value=mock_session)):
            await orch.execute_chat("and Y?", "c1")

        history_text = mock_session.execute.call_args.kwargs["history_text"]
        assert history_text == "User: what is X?\nAssistant: X is foo.\n"

    @pytest.mark.anyio
    async def test_history_disabled_passes_empty_collections(self):
        cs = mock_client_settings(chat_history=False)
        orch = _make_orchestrator(cs=cs)
        orch.history.append("c1", "user", "prior")
        orch.history.append("c1", "assistant", "prior reply")

        mock_session = MagicMock(spec=AgentGraphSession)
        mock_session.chat = AsyncMock(return_value="answer")
        mock_session.last_metadata = SessionMetadata()

        with patch.object(orch, "_build_session", AsyncMock(return_value=mock_session)):
            await orch.execute_chat("new turn", "c1")

        assert mock_session.chat.call_args.kwargs["history_messages"] == []

    @pytest.mark.anyio
    async def test_route_switch_sees_full_history_without_migration(self):
        """The 'I am Driver 1' bug: switching mode mid-conversation must
        still surface prior turns without any per-session migration."""
        cs = mock_client_settings(chat_history=True)
        orch = _make_orchestrator(cs=cs)

        llm_only_session = MagicMock(spec=AgentGraphSession)
        llm_only_session.chat = AsyncMock(return_value="ack driver 1")
        llm_only_session.last_metadata = SessionMetadata()

        nl2sql_session = MagicMock(spec=NL2SQLGraphSession)
        nl2sql_session.chat = AsyncMock(return_value="apex dynamics")
        nl2sql_session.last_metadata = SessionMetadata()

        builds = iter([llm_only_session, nl2sql_session])

        async def fake_build(_cs, _route, **_kwargs):
            return next(builds)

        with patch.object(orch, "_build_session", side_effect=fake_build):
            await orch.execute_chat("I am Driver 1.", "c1")
            cs.tools_enabled = ["NL2SQL"]
            cs.model_dump.return_value = {**cs.model_dump(), "tools_enabled": ["NL2SQL"]}
            await orch.execute_chat("Which team?", "c1")

        passed = nl2sql_session.chat.call_args.kwargs["history_messages"]
        assert [m.content for m in passed] == ["I am Driver 1.", "ack driver 1"]

    @pytest.mark.anyio
    async def test_turns_captured_while_disabled_are_not_replayed(self):
        """Toggling chat_history off then on must not resurface the off-turn
        as LLM context — the pre-refactor `AgentGraphSession.chat` skipped
        appending to its conversation buffer when chat_history was False,
        and the new orchestrator-owned feed must match that.
        """
        cs = mock_client_settings(chat_history=False)
        orch = _make_orchestrator(cs=cs)

        mock_session = MagicMock(spec=AgentGraphSession)
        mock_session.chat = AsyncMock(return_value="ack private")
        mock_session.last_metadata = SessionMetadata()

        with patch.object(orch, "_build_session", AsyncMock(return_value=mock_session)):
            await orch.execute_chat("private turn", "c1")

            cs.ll_model.chat_history = True
            cs.model_dump.return_value = {
                **cs.model_dump(),
                "ll_model": {**cs.model_dump()["ll_model"], "chat_history": True},
            }
            await orch.execute_chat("new turn", "c1")

        passed = mock_session.chat.call_args.kwargs["history_messages"]
        contents = [m.content for m in passed]
        assert "private turn" not in contents, contents
        assert "ack private" not in contents, contents

    @pytest.mark.anyio
    async def test_combined_session_receives_both_history_forms(self):
        cs = mock_client_settings(chat_history=True, tools_enabled=["NL2SQL", "Vector Search"])
        orch = _make_orchestrator(cs=cs)
        orch.history.append("c1", "user", "earlier")
        orch.history.append("c1", "assistant", "earlier reply")

        mock_session = MagicMock(spec=CombinedSession)
        mock_session.execute = AsyncMock(return_value="answer")
        mock_session.last_metadata = SessionMetadata()

        with patch.object(orch, "_build_session", AsyncMock(return_value=mock_session)):
            await orch.execute_chat("now", "c1")

        kwargs = mock_session.execute.call_args.kwargs
        assert kwargs["history_text"] == "User: earlier\nAssistant: earlier reply\n"
        assert [m.content for m in kwargs["history_messages"]] == ["earlier", "earlier reply"]


class TestNL2SQLDdsRouting:
    """The NL2SQL factory routes the SQLcl connection through the DDS effective alias."""

    @pytest.mark.anyio
    async def test_session_uses_effective_alias(self):
        """connection_name comes from resolve_effective_tool_alias(client), not the raw owner alias."""
        orch = _make_orchestrator()
        graph = mock_compiled_graph()
        with (
            patch("server.app.runtime.langgraph.chat.build_nl2sql_graph", AsyncMock(return_value=graph)),
            patch("server.app.runtime.langgraph.chat.resolve_effective_tool_alias", return_value="CORE::SCOUT1"),
        ):
            session = await orch._build_nl2sql_agent_session(mock_client_settings(), client="c1")
        assert "connection_name: CORE::SCOUT1" in session._db_context

    @pytest.mark.anyio
    async def test_session_connects_configured_database_before_chat(self):
        """The orchestrator must wire the configured database connect step into NL2SQL sessions."""
        orch = _make_orchestrator()
        graph = mock_compiled_graph(result={"messages": [AIMessage(content="sql result")]})
        events: list[str] = []

        async def fake_connect(server_url, api_key, connection_name, model, thread_id=None):
            events.append("connect")

        async def fake_ainvoke(*_args, **_kwargs):
            events.append("graph")
            return {"messages": [AIMessage(content="sql result")]}

        graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)

        with (
            patch("server.app.runtime.langgraph.chat.build_nl2sql_graph", AsyncMock(return_value=graph)),
            patch(
                "server.app.runtime.langgraph.chat.connect_sqlcl_database",
                side_effect=fake_connect,
            ) as connect_patch,
        ):
            session = await orch._build_nl2sql_agent_session(mock_client_settings(), client="c1")
            result = await session.chat("How many tables?")

        assert result == "sql result"
        assert events == ["connect", "graph"]
        connect_patch.assert_awaited_once_with(
            "http://127.0.0.1:8000/mcp",
            "test-key",
            "CORE",
            TEST_OLLAMA_MODEL_KEY,
            thread_id="c1",
        )

    @pytest.mark.anyio
    async def test_session_build_propagates_dds_error(self):
        """An active-but-unusable DDS override raises before the agent gets a connection_name."""
        orch = _make_orchestrator()
        graph = mock_compiled_graph()
        with (
            patch("server.app.runtime.langgraph.chat.build_nl2sql_graph", AsyncMock(return_value=graph)),
            patch(
                "server.app.runtime.langgraph.chat.resolve_effective_tool_alias",
                side_effect=DdsConnectionError("unavailable"),
            ),
            pytest.raises(DdsConnectionError),
        ):
            await orch._build_nl2sql_agent_session(mock_client_settings(), client="c1")
