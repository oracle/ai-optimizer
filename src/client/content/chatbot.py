"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Session States Set:
- user_client: Stores the Client
"""
# spell-checker:ignore streamlit oraclevs

import asyncio
import base64
import inspect
import json
import re

import streamlit as st
from streamlit import session_state as state

from client.content.config.tabs.models import get_models
from client.utils import st_common, api_call, client, vs_options, tool_options
from client.utils.st_footer import render_chat_footer
from common import logging_config

logger = logging_config.logging.getLogger("client.content.chatbot")


#############################################################################
# Functions
#############################################################################
def escape_markdown_latex(text: str) -> str:
    r"""Convert LaTeX math delimiters to markdown-compatible format.

    Handles:
    - LaTeX display math \[ \] → $$ $$
    - LaTeX inline math \( \) → $ $
    - Square brackets with LaTeX commands [ ... ] → $$ $$ (fallback for missing backslashes)
    - Cleans up stray $ signs within LaTeX expressions
    """
    if not text:
        return text

    # Convert LaTeX display math delimiters: \[ \] → $$ $$
    text = re.sub(r"\\\[", "$$", text)
    text = re.sub(r"\\\]", "$$", text)

    # Convert LaTeX inline math delimiters: \( \) → $ $
    text = re.sub(r"\\\(", "$", text)
    text = re.sub(r"\\\)", "$", text)

    # Fallback: Convert [ ... ] to $$ $$ if it contains LaTeX commands
    # This handles cases where backslashes are stripped before reaching here
    text = re.sub(r"\[\s*(\\[a-zA-Z]+)", r"$$ \1", text)
    text = re.sub(r"(\\[a-zA-Z]+[^\]]*)\s*\]", r"\1 $$", text)

    # Clean up stray $ signs within LaTeX expressions that break rendering
    # Find sequences that have LaTeX commands with partial $ wrapping and fix them
    # Pattern: matches text with LaTeX commands that have $ signs interspersed incorrectly
    def clean_stray_dollars(match):
        """Remove $ signs from within LaTeX expression and wrap the whole thing"""
        content = match.group(1)
        # Remove all $ signs from within the expression
        cleaned = content.replace("$", "")
        return f"${cleaned}$"

    # Match sequences that contain LaTeX commands mixed with $ signs
    # This catches: "M = 330,000 $\times \frac{...}$"
    text = re.sub(
        r"(?<!\$)([^$\n]*\\[a-zA-Z]+[^$\n]*\$[^$\n]*\\[a-zA-Z]+[^$\n]*?)(?=\s|$|\n)", clean_stray_dollars, text
    )

    return text


def show_vector_search_refs(context, vs_metadata=None) -> None:
    """When Vector Search Content Found, show the references"""
    st.markdown("**References:**")
    ref_src = set()
    ref_cols = st.columns([3, 3, 3])
    # Create a button in each column
    for i, (ref_col, chunk) in enumerate(zip(ref_cols, context["documents"])):
        chunk = context["documents"][i]

        # Get similarity score if available
        similarity_score = chunk.get("metadata", {}).get("similarity_score")

        # Create popover label with score if available
        if similarity_score is not None:
            popover_label = f"Reference {i + 1} ({similarity_score:.2f})"
        else:
            popover_label = f"Reference: {i + 1}"

        with ref_col.popover(popover_label):
            logger.debug("Chunk Content: %s", chunk)

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

    # Display Vector Search details in expander
    if vs_metadata or ref_src:
        with st.expander("Vector Search Details", expanded=False):
            if ref_src:
                st.markdown("**Source Documents:**")
                for link in ref_src:
                    st.markdown(f"- {link}")

            if vs_metadata and vs_metadata.get("searched_tables"):
                st.markdown("**Tables Searched:**")
                for table in vs_metadata["searched_tables"]:
                    st.markdown(f"- {table}")

            if vs_metadata and vs_metadata.get("context_input"):
                st.markdown(f"**Search Query:** {vs_metadata.get('context_input')}")


def show_token_usage(token_usage) -> None:
    """Display token usage for AI responses using caption"""
    if token_usage:
        prompt_tokens = token_usage.get("prompt_tokens", 0)
        completion_tokens = token_usage.get("completion_tokens", 0)
        total_tokens = token_usage.get("total_tokens", 0)
        st.caption(f"Token usage: {prompt_tokens} prompt + {completion_tokens} completion = {total_tokens} total")


def setup_sidebar():
    """Configure sidebar settings"""
    ll_models_enabled = st_common.enabled_models_lookup("ll")
    if not ll_models_enabled:
        st.error("No language models are configured and/or enabled. Disabling Client.", icon="🛑")
        st.stop()

    state.enable_client = True
    tool_options.tools_sidebar()
    st_common.history_sidebar()
    st_common.ll_sidebar()
    vs_options.vector_search_sidebar()

    if not state.enable_client:
        st.stop()


def create_client():
    """Create or get existing client"""
    if "user_client" not in state:
        state.user_client = client.Client(
            server=state.server,
            settings=state.client_settings,
            timeout=1200,
        )
    return state.user_client


def display_chat_history(history):
    """Display chat history messages with metadata"""
    st.chat_message("ai").write("Hello, how can I help you?")
    vector_search_refs = {}

    for message in history or []:
        if not message["content"]:
            continue

        # Store vector search references for next AI message
        if message["role"] == "tool" and message["name"] == "optimizer_vs-retriever":
            vector_search_refs = json.loads(message["content"])
            continue
        # Display AI assistant messages
        if message["role"] in ("ai", "assistant") and not message.get("tool_calls"):
            with st.chat_message("ai"):
                st.markdown(escape_markdown_latex(message["content"]))
                response_metadata = message.get("response_metadata", {})
                token_usage = response_metadata.get("token_usage", {})
                if token_usage:
                    show_token_usage(token_usage)

                # Show vector search references if available
                if vector_search_refs and vector_search_refs.get("documents"):
                    show_vector_search_refs(vector_search_refs, response_metadata.get("vs_metadata", {}))
                    vector_search_refs = {}
            continue

        # Display human user messages
        if message["role"] in ("human", "user"):
            with st.chat_message("human"):
                content = message["content"]
                # Handle list content with text and images
                if isinstance(content, list):
                    for part in content:
                        if part["type"] == "text":
                            st.write(part["text"])
                        elif part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image"):
                            st.image(part["image_url"]["url"])
                else:
                    st.write(content)


async def handle_chat_input(user_client):
    """Handle user chat input and streaming response"""
    render_chat_footer()

    if human_request := st.chat_input(
        "Ask your question here... ",
        accept_file=True,
        file_type=["jpg", "jpeg", "png"],
    ):
        st.chat_message("human").write(human_request.text)
        file_b64 = None

        if human_request["files"]:
            file = human_request["files"][0]
            file_bytes = file.read()
            file_b64 = base64.b64encode(file_bytes).decode("utf-8")

        try:
            message_placeholder = st.chat_message("ai").empty()
            full_answer = ""

            # Animated thinking indicator
            async def animate_thinking():
                """Animate the thinking indicator with increasing dots"""
                dots = 0
                while True:
                    message_placeholder.markdown(f"🤔 Thinking{'.' * (dots % 4)}")
                    dots += 1
                    await asyncio.sleep(0.5)  # Update every 500ms

            # Start the thinking animation
            thinking_task = asyncio.create_task(animate_thinking())

            try:
                async for chunk in user_client.stream(message=human_request.text, image_b64=file_b64):
                    # Cancel thinking animation on first chunk
                    if thinking_task and not thinking_task.done():
                        thinking_task.cancel()
                        thinking_task = None
                    full_answer += chunk
                    message_placeholder.markdown(escape_markdown_latex(full_answer))
            finally:
                # Ensure thinking task is cancelled
                if thinking_task and not thinking_task.done():
                    thinking_task.cancel()

            st.rerun()
        except (ConnectionError, TimeoutError, api_call.ApiError) as ex:
            logger.exception("Error during chat streaming: %s", ex)
            message_placeholder.markdown("An unexpected error occurred, please retry your request.")
            if st.button("Retry", key="reload_chatbot"):
                st_common.clear_state_key("user_client")
                st.rerun()


#############################################################################
# MAIN
#############################################################################
def show_prompt_engineering_notice():
    """Show notice when both tools are enabled and default prompt is being used"""
    tools_enabled = state.client_settings.get("tools_enabled", [])
    both_tools_enabled = "Vector Search" in tools_enabled and "NL2SQL" in tools_enabled

    if both_tools_enabled:
        try:
            # Check if the prompt has been customized
            response = api_call.get(endpoint="v1/mcp/prompts/optimizer_tools-default/has-override")
            has_override = response.get("has_override", False)

            # Only show notice if using default prompt (no customization)
            if not has_override:
                st.info(
                    "**Responses not as you expected?** Default Tools Prompt Engineering maybe required.", icon="💡"
                )
        except (api_call.ApiError, KeyError):
            # Silently fail - don't show notice if we can't check
            pass


async def main() -> None:
    """Streamlit GUI"""
    try:
        get_models()
    except api_call.ApiError:
        st.stop()

    setup_sidebar()
    show_prompt_engineering_notice()
    user_client = create_client()
    history = await user_client.get_history()
    display_chat_history(history)
    await handle_chat_input(user_client)


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    try:
        asyncio.run(main())
    except ValueError as ex:
        logger.exception("Bug detected: %s", ex)
        st.error("It looks like you found a bug; please open an issue", icon="🛑")
        st.stop()
    except IndexError as ex:
        logger.exception("Unable to contact the server: %s", ex)
        st.error("Unable to contact the server, is it running?", icon="🚨")
        if st.button("Retry", key="reload_chatbot"):
            st_common.clear_state_key("user_client")
            st.rerun()
