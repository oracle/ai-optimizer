"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit selectbox

import asyncio
import json
import logging
import re

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core import sidebar
from client.app.core.api import _base_url, _headers
from client.app.core.helpers import extract_error_detail, load_chat_history
from net_addressing import verify_for_url

LOGGER = logging.getLogger("content.chatbot")


#####################################################
# Functions
#####################################################
_CODE_SPAN_RE = re.compile(r"(```.*?```|`[^`]+`)", re.DOTALL)
_MATH_RE = re.compile(r"(\$\$.+?\$\$|\$(?!\s).+?(?<!\s)\$)", re.DOTALL)


def escape_markdown_latex(text: str) -> str:
    r"""Convert LaTeX math delimiters and escape bare $ signs for Streamlit.

    Skips content inside fenced code blocks and inline code spans.
    Preserves numeric citations like \[1\].
    """
    if not text:
        return text

    def _process_segment(segment: str) -> str:
        # Display math: \[...\] → $$...$$ (skip if content is a numeric citation)
        segment = re.sub(
            r"\\\[(.*?)\\\]",
            lambda m: (m.group(0) if re.fullmatch(r"[\d,;\s\-\u2013\u2014]+", m.group(1)) else f"$${m.group(1)}$$"),
            segment,
            flags=re.DOTALL,
        )
        # Escape bare $ not part of matched math pairs (before \(...\) conversion
        # so that newly introduced $ delimiters are never subject to escaping)
        math_parts = _MATH_RE.split(segment)
        for i, part in enumerate(math_parts):
            if not _MATH_RE.fullmatch(part):
                math_parts[i] = part.replace("$", r"\$")
        segment = "".join(math_parts)

        # Inline math: \(...\) → $...$ (after bare-$ escaping so spaces are fine)
        segment = re.sub(r"\\\((.*?)\\\)", r"$\1$", segment, flags=re.DOTALL)
        return segment

    # Split on code spans — only process non-code parts
    parts = _CODE_SPAN_RE.split(text)
    for i, part in enumerate(parts):
        if not _CODE_SPAN_RE.fullmatch(part):
            parts[i] = _process_segment(part)
    return "".join(parts)


def _extract_search_query(raw: str) -> str:
    """Extract a display-friendly search query from context_input.

    In the LangGraph runtime the rephrase output is wrapped in LangChain
    content blocks before reaching the retriever, so context_input may be:
      '[{"type":"text","text":"{\\"rephrased_prompt\\":\\"..\\"}","id":"lc_..."}]'
    This unwraps content blocks and/or RephrasePrompt JSON to return the
    actual query string.
    """
    try:
        parsed = json.loads(raw)
        # Unwrap LangChain content blocks
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and parsed[0].get("type") == "text":
            text = parsed[0]["text"]
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
        # Extract rephrased_prompt from RephrasePrompt dict
        if isinstance(parsed, dict) and "rephrased_prompt" in parsed:
            return parsed["rephrased_prompt"]
    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        pass
    return raw


def show_vector_search_refs(vs_metadata: dict) -> None:
    """Display vector search document references as popovers with an expander for details."""
    documents = [doc for doc in vs_metadata.get("documents", []) if doc.get("page_content")]
    ref_src: set[str] = set()

    if documents:
        st.markdown("**References:**")
        ref_cols = st.columns([3, 3, 3])

        for i, (ref_col, chunk) in enumerate(zip(ref_cols, documents)):
            similarity_score = chunk.get("metadata", {}).get("similarity_score")
            popover_label = (
                f"Reference {i + 1} ({similarity_score:.2f})" if similarity_score is not None else f"Reference: {i + 1}"
            )

            with ref_col.popover(popover_label):
                LOGGER.debug("Chunk Content: %s", chunk)
                st.subheader("Reference Text", divider="red")
                st.markdown(chunk["page_content"])
                metadata = chunk.get("metadata", {})
                filename = metadata.get("filename")
                if filename:
                    ref_src.add(filename)
                st.subheader("Metadata", divider="red")
                st.markdown(f"Document:  {metadata.get('source', 'N/A')}")
                st.markdown(f"Document Page:  {metadata.get('page_label', 'N/A')}")
                st.markdown(f"Vector Storage Chunk: {metadata.get('page', 'N/A')}")
                st.markdown(
                    f"Similarity Score: {similarity_score:.3f}"
                    if similarity_score is not None
                    else "Similarity Score: N/A"
                )

    with st.expander("Vector Search Details", expanded=False):
        if ref_src:
            st.markdown("**Source Documents:**")
            for link in ref_src:
                st.markdown(f"- {link}")
        if vs_metadata.get("searched_tables"):
            st.markdown("**Tables Searched:**")
            for table in vs_metadata["searched_tables"]:
                st.markdown(f"- {table}")
        if vs_metadata.get("context_input"):
            st.markdown(f"**Search Query:** {_extract_search_query(vs_metadata['context_input'])}")


def show_sql_details(sql_metadata: dict) -> None:
    """Display executed SQL statements for NL2SQL responses."""
    executed_sql = [sql for sql in sql_metadata.get("executed_sql", []) if sql]
    if not executed_sql:
        return

    with st.expander("SQL Details", expanded=False):
        for sql in executed_sql:
            st.markdown("```sql\n" + sql + "\n```")


async def _stream_chat(messages: list[dict], metadata: dict):
    """Async generator that streams SSE chunks from the chat/streams endpoint.

    The *metadata* dict is populated with ``token_usage`` from the completion
    event (if present) so callers can display it after streaming finishes.
    """
    url = f"{_base_url()}/chat/streams"
    headers = {**_headers(), "client": state.optimizer_client}
    body = {"messages": messages}

    async with httpx.AsyncClient(timeout=120, verify=verify_for_url(url)) as client:  # noqa: SIM117
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event, buffer = buffer.split("\n\n", 1)
                    for line in event.split("\n"):
                        line = line.strip()  # noqa: PLW2901
                        if not line.startswith("data: "):
                            continue
                        payload = line[len("data: ") :]
                        if payload == "[DONE]":
                            return
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") == "error":
                            raise RuntimeError(data.get("content", "An error occurred"))
                        if data.get("type") == "completion":
                            token_usage = data.get("token_usage")
                            if token_usage:
                                metadata["token_usage"] = token_usage
                            vs_metadata = data.get("vs_metadata")
                            if vs_metadata:
                                metadata["vs_metadata"] = vs_metadata
                            sql_metadata = data.get("sql_metadata")
                            if sql_metadata:
                                metadata["sql_metadata"] = sql_metadata
                        if data.get("type") == "stream":
                            yield data.get("content", "")


async def _handle_chat(user_input: str) -> None:
    """Handle chat input with animated thinking indicator and streaming response."""
    with st.chat_message("assistant"):
        try:
            placeholder = st.empty()
            full_response = ""
            metadata: dict = {}

            # Animated thinking indicator
            async def animate_thinking():
                dots = 0
                while True:
                    placeholder.markdown(f"🤔 Thinking{'.' * (dots % 4)}")
                    dots += 1
                    await asyncio.sleep(0.5)

            thinking_task = asyncio.create_task(animate_thinking())

            try:
                async for chunk in _stream_chat([{"role": "user", "content": user_input}], metadata):
                    if thinking_task and not thinking_task.done():
                        thinking_task.cancel()
                        thinking_task = None
                    full_response += chunk
                    placeholder.markdown(escape_markdown_latex(full_response))
            finally:
                if thinking_task and not thinking_task.done():
                    thinking_task.cancel()

            token_usage = metadata.get("token_usage")
            if token_usage:
                st.caption(
                    f"Token usage: {token_usage['prompt_tokens']} prompt"
                    f" + {token_usage['completion_tokens']} completion"
                    f" = {token_usage['total_tokens']} total"
                )
            resp_vs_meta = metadata.get("vs_metadata")
            if resp_vs_meta:
                show_vector_search_refs(resp_vs_meta)
            resp_sql_meta = metadata.get("sql_metadata")
            if resp_sql_meta:
                show_sql_details(resp_sql_meta)
        except httpx.HTTPStatusError as exc:
            st.error(extract_error_detail(exc))
        except httpx.ReadTimeout:
            st.error("Response timed out. Please try again.")
        except httpx.HTTPError as exc:
            LOGGER.warning("Chat stream request failed: %s", exc)
            st.error("Unable to connect to the server. Please check that the server is running.")
        except RuntimeError as exc:
            st.error(str(exc))


#####################################################
# Sidebar
#####################################################
sidebar.toolkit_sidebar()
sidebar.history_sidebar()
model_options = sidebar.lm_sidebar()
sidebar.vector_search_sidebar()
#####################################################
# Chat Area
#####################################################
if not model_options:
    st.error("No language models are configured and/or enabled. Disabling Client.", icon="🛑")
    st.stop()

if not state.get("enable_client", True):
    st.stop()

chat_messages = load_chat_history(state.optimizer_client)

st.chat_message("assistant").write("Hello, how can I help you?")

for msg in chat_messages:
    with st.chat_message(msg["role"]):
        st.markdown(escape_markdown_latex(msg["content"]))
        if msg.get("token_usage"):
            tu = msg["token_usage"]
            st.caption(
                f"Token usage: {tu['prompt_tokens']} prompt"
                f" + {tu['completion_tokens']} completion"
                f" = {tu['total_tokens']} total"
            )
        vs_meta = msg.get("vs_metadata")
        if vs_meta:
            show_vector_search_refs(vs_meta)
        sql_meta = msg.get("sql_metadata")
        if sql_meta:
            show_sql_details(sql_meta)

if prompt := st.chat_input("Ask a question...", disabled=not model_options):
    with st.chat_message("user"):
        st.markdown(prompt)

    asyncio.run(_handle_chat(prompt))
