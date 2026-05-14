"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for LangGraph ChatOrchestrator.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.api.v1.schemas.chat import TokenUsage, VsMetadata
from server.app.runtime.common import LLMConfigurationError, SessionMetadata
from server.app.runtime.langgraph.chat import ChatOrchestrator
from server.app.runtime.langgraph.multi_tool import CombinedSession
from server.app.runtime.langgraph.session import (
    AgentGraphSession,
    GraphFlowSession,
    NL2SQLGraphSession,
)
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
# TestConversationIdPreservation
# ---------------------------------------------------------------------------


def _make_agent_session(conversation_id=None, checkpointer=None):
    """Build a real AgentGraphSession with a mock graph."""
    return AgentGraphSession(mock_compiled_graph(), conversation_id=conversation_id, checkpointer=checkpointer)


def _make_nl2sql_session(cs=None, thread_id="", conversation_id=None, checkpointer=None):
    """Build a real NL2SQLGraphSession with a mock graph."""
    if cs is None:
        from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ

        cs = SAMPLE_CLIENT_SETTINGS_OBJ
    return NL2SQLGraphSession(
        MagicMock(),
        cs,
        thread_id=thread_id,
        conversation_id=conversation_id,
        checkpointer=checkpointer,
    )


def _make_combined_session(nl2sql_session=None):
    """Build a CombinedSession with mock sub-sessions."""
    vs = MagicMock(spec=GraphFlowSession)
    vs.history = ""
    if nl2sql_session is None:
        nl2sql_session = _make_nl2sql_session(thread_id="c1")
    return CombinedSession(
        vs,
        nl2sql_session,
        "ollama/qwen3:8b",
        "system prompt",
    )


class TestConversationIdPreservation:
    """Verify conversation_id is preserved when sessions are rebuilt."""

    @pytest.mark.anyio
    async def test_session_rebuilt_preserves_conversation_id(self):
        """Settings change rebuild preserves agent session conversation_id."""
        cs = mock_client_settings(chat_history=True)
        orch = _make_orchestrator(cs=cs)

        original_session = _make_agent_session()
        original_id = original_session.conversation_id

        new_session = _make_agent_session()
        build_mock = AsyncMock(side_effect=[original_session, new_session])

        with patch.object(orch, "_build_session", build_mock):
            await orch.execute_chat("q1", "c1")

            # Change a setting to trigger rebuild
            cs.model_dump.return_value = {
                **cs.model_dump(),
                "ll_model": {**cs.model_dump()["ll_model"], "temperature": 0.99},
            }
            # Patch chat on new_session so execute_chat works
            new_session.chat = AsyncMock(return_value="reply")
            new_session.last_metadata = SessionMetadata()
            original_session.chat = AsyncMock(return_value="reply")
            original_session.last_metadata = SessionMetadata()

            await orch.execute_chat("q2", "c1")

        # The new session should have the original conversation_id
        assert new_session.conversation_id == original_id

    @pytest.mark.anyio
    async def test_refresh_prompts_preserves_agent_conversation_id(self):
        """refresh_prompts preserves agent session conversation_id."""
        orch = _make_orchestrator()
        original_session = _make_agent_session()
        original_id = original_session.conversation_id
        cs_dict = mock_client_settings().model_dump()

        orch._session_cache[("c1", "llm_only")] = (original_session, cs_dict, orch._build_identity(cs_dict))

        new_session = _make_agent_session()
        with patch.object(orch, "_build_agent_session", AsyncMock(return_value=new_session)):
            await orch.refresh_prompts()

        rebuilt = orch._session_cache[("c1", "llm_only")][0]
        assert isinstance(rebuilt, AgentGraphSession)
        assert rebuilt.conversation_id == original_id

    @pytest.mark.anyio
    async def test_refresh_prompts_preserves_combined_nl2sql_conversation_id(self):
        """refresh_prompts preserves nl2sql sub-session conversation_id in combined."""
        orch = _make_orchestrator()
        nl2sql = _make_nl2sql_session(thread_id="c1")
        original_nl2sql_id = nl2sql.conversation_id
        combined = _make_combined_session(nl2sql_session=nl2sql)
        cs_dict = mock_client_settings().model_dump()

        orch._session_cache[("c1", "combined")] = (combined, cs_dict, orch._build_identity(cs_dict))

        new_nl2sql = _make_nl2sql_session(thread_id="c1")
        new_combined = _make_combined_session(nl2sql_session=new_nl2sql)
        with patch.object(orch, "_build_combined_session", AsyncMock(return_value=new_combined)):
            await orch.refresh_prompts()

        rebuilt = orch._session_cache[("c1", "combined")][0]
        assert isinstance(rebuilt, CombinedSession)
        assert rebuilt.nl2sql_session.conversation_id == original_nl2sql_id

    @pytest.mark.anyio
    async def test_settings_change_preserves_combined_nl2sql_conversation_id(self):
        """Settings-change rebuild preserves nl2sql sub-session conversation_id in combined."""
        cs = mock_client_settings(tools_enabled=["NL2SQL", "Vector Search"])
        orch = _make_orchestrator(cs=cs)

        nl2sql = _make_nl2sql_session(thread_id="c1")
        original_nl2sql_id = nl2sql.conversation_id
        original_combined = _make_combined_session(nl2sql_session=nl2sql)
        original_combined.execute = AsyncMock(return_value="reply")
        original_combined.last_metadata = SessionMetadata()

        new_nl2sql = _make_nl2sql_session(thread_id="c1")
        new_combined = _make_combined_session(nl2sql_session=new_nl2sql)
        new_combined.execute = AsyncMock(return_value="reply2")
        new_combined.last_metadata = SessionMetadata()

        build_mock = AsyncMock(side_effect=[original_combined, new_combined])

        with patch.object(orch, "_build_session", build_mock):
            await orch.execute_chat("q1", "c1")

            # Change a setting to trigger rebuild
            cs.model_dump.return_value = {
                **cs.model_dump(),
                "ll_model": {**cs.model_dump()["ll_model"], "temperature": 0.99},
            }

            await orch.execute_chat("q2", "c1")

        assert new_combined.nl2sql_session.conversation_id == original_nl2sql_id


# ---------------------------------------------------------------------------
# TestCheckpointerPreservation
# ---------------------------------------------------------------------------


class TestCheckpointerPreservation:
    """Verify checkpointer is preserved when sessions are rebuilt."""

    @pytest.mark.anyio
    async def test_settings_change_preserves_checkpointer(self):
        """Settings change rebuild preserves agent session checkpointer."""
        cs = mock_client_settings(chat_history=True)
        orch = _make_orchestrator(cs=cs)

        sentinel_cp = MagicMock(name="sentinel_checkpointer")
        original_session = _make_agent_session(checkpointer=sentinel_cp)
        original_session.chat = AsyncMock(return_value="reply")
        original_session.last_metadata = SessionMetadata()

        # First build returns original_session
        build_count = 0

        async def fake_build(
            _cs_dict,
            _route,
            **_kwargs,
        ):
            nonlocal build_count
            build_count += 1
            if build_count == 1:
                return original_session
            # Second build: verify checkpointer is passed through
            new_session = _make_agent_session(checkpointer=_kwargs.get("checkpointer"))
            new_session.chat = AsyncMock(return_value="reply2")
            new_session.last_metadata = SessionMetadata()
            return new_session

        with patch.object(orch, "_build_session", side_effect=fake_build):
            await orch.execute_chat("q1", "c1")

            # Change a setting to trigger rebuild
            cs.model_dump.return_value = {
                **cs.model_dump(),
                "ll_model": {**cs.model_dump()["ll_model"], "temperature": 0.99},
            }
            await orch.execute_chat("q2", "c1")

        rebuilt = orch._session_cache[("c1", "llm_only")][0]
        assert isinstance(rebuilt, AgentGraphSession)
        assert rebuilt.checkpointer is sentinel_cp

    @pytest.mark.anyio
    async def test_refresh_prompts_preserves_agent_checkpointer(self):
        """refresh_prompts preserves agent session checkpointer."""
        orch = _make_orchestrator()
        sentinel_cp = MagicMock(name="sentinel_checkpointer")
        original_session = _make_agent_session(checkpointer=sentinel_cp)
        cs_dict = mock_client_settings().model_dump()

        orch._session_cache[("c1", "llm_only")] = (original_session, cs_dict, orch._build_identity(cs_dict))

        new_session = _make_agent_session()

        async def fake_build(_cs, checkpointer=None):
            new_session._checkpointer = checkpointer
            return new_session

        with patch.object(orch, "_build_agent_session", side_effect=fake_build):
            await orch.refresh_prompts()

        rebuilt = orch._session_cache[("c1", "llm_only")][0]
        assert isinstance(rebuilt, AgentGraphSession)
        assert rebuilt.checkpointer is sentinel_cp

    @pytest.mark.anyio
    async def test_refresh_prompts_preserves_combined_nl2sql_checkpointer(self):
        """refresh_prompts preserves nl2sql sub-session checkpointer in combined."""
        orch = _make_orchestrator()
        sentinel_cp = MagicMock(name="sentinel_nl2sql_cp")
        nl2sql = _make_nl2sql_session(thread_id="c1", checkpointer=sentinel_cp)
        combined = _make_combined_session(nl2sql_session=nl2sql)
        cs_dict = mock_client_settings().model_dump()

        orch._session_cache[("c1", "combined")] = (combined, cs_dict, orch._build_identity(cs_dict))

        new_nl2sql = _make_nl2sql_session(thread_id="c1")
        new_combined = _make_combined_session(nl2sql_session=new_nl2sql)

        async def fake_build(_cs, **_kwargs):
            new_combined.nl2sql_session._checkpointer = _kwargs.get("nl2sql_checkpointer")
            return new_combined

        with patch.object(orch, "_build_combined_session", side_effect=fake_build):
            await orch.refresh_prompts()

        rebuilt = orch._session_cache[("c1", "combined")][0]
        assert isinstance(rebuilt, CombinedSession)
        assert rebuilt.nl2sql_session.checkpointer is sentinel_cp

    @pytest.mark.anyio
    async def test_settings_change_preserves_combined_nl2sql_checkpointer(self):
        """Settings-change rebuild preserves nl2sql sub-session checkpointer in combined."""
        cs = mock_client_settings(tools_enabled=["NL2SQL", "Vector Search"])
        orch = _make_orchestrator(cs=cs)

        sentinel_cp = MagicMock(name="sentinel_nl2sql_cp")
        nl2sql = _make_nl2sql_session(thread_id="c1", checkpointer=sentinel_cp)
        original_combined = _make_combined_session(nl2sql_session=nl2sql)
        original_combined.execute = AsyncMock(return_value="reply")
        original_combined.last_metadata = SessionMetadata()

        build_count = 0

        async def fake_build(
            _cs_dict,
            _route,
            **_kwargs,
        ):
            nonlocal build_count
            build_count += 1
            if build_count == 1:
                return original_combined
            new_nl2sql = _make_nl2sql_session(thread_id="c1", checkpointer=_kwargs.get("nl2sql_checkpointer"))
            new_combined = _make_combined_session(nl2sql_session=new_nl2sql)
            new_combined.execute = AsyncMock(return_value="reply2")
            new_combined.last_metadata = SessionMetadata()
            return new_combined

        with patch.object(orch, "_build_session", side_effect=fake_build):
            await orch.execute_chat("q1", "c1")

            cs.model_dump.return_value = {
                **cs.model_dump(),
                "ll_model": {**cs.model_dump()["ll_model"], "temperature": 0.99},
            }
            await orch.execute_chat("q2", "c1")

        rebuilt = orch._session_cache[("c1", "combined")][0]
        assert isinstance(rebuilt, CombinedSession)
        assert rebuilt.nl2sql_session.checkpointer is sentinel_cp
