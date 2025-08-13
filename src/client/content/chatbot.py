"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This file merges the Streamlit Chatbot GUI with the MCPClient for a complete,
runnable example demonstrating their integration.
"""

# spell-checker:ignore streamlit, oraclevs, selectai, langgraph, prebuilt
import asyncio
import inspect
import json
import base64

import streamlit as st
from streamlit import session_state as state

from client.content.config.models import get_models

import client.utils.st_common as st_common
import client.utils.api_call as api_call

from client.utils.st_footer import render_chat_footer
import common.logging_config as logging_config
from client.mcp.client import MCPClient
from pathlib import Path

logger = logging_config.logging.getLogger("client.content.chatbot")


#############################################################################
# Functions
#############################################################################
def show_vector_search_refs(context):
    """When Vector Search Content Found, show the references"""
    st.markdown("**References:**")
    ref_src = set()
    ref_cols = st.columns([3, 3, 3])
    # Create a button in each column
    for i, (ref_col, chunk) in enumerate(zip(ref_cols, context[0])):
        with ref_col.popover(f"Reference: {i + 1}"):
            chunk = context[0][i]
            logger.debug("Chunk Content: %s", chunk)
            st.subheader("Reference Text", divider="red")
            st.markdown(chunk["page_content"])
            try:
                ref_src.add(chunk["metadata"]["filename"])
                st.subheader("Metadata", divider="red")
                st.markdown(f"File:  {chunk['metadata']['source']}")
                st.markdown(f"Chunk: {chunk['metadata']['page']}")
            except KeyError:
                logger.error("Chunk Metadata NOT FOUND!!")

    for link in ref_src:
        st.markdown("- " + link)
    st.markdown(f"**Notes:** Vector Search Query - {context[1]}")


#############################################################################
# Helper Functions
#############################################################################
def setup_sidebar():
    """Initialize and validate sidebar components"""
    ll_models_enabled = st_common.enabled_models_lookup("ll")
    if not ll_models_enabled:
        st.error("No language models are configured and/or enabled. Disabling Client.", icon="🛑")
        st.stop()
    state.enable_client = True
    st_common.tools_sidebar()
    st_common.history_sidebar()
    st_common.ll_sidebar()
    st_common.selectai_sidebar()
    st_common.vector_search_sidebar()
    if not state.enable_client:
        st.stop()

def display_messages():
    """Render chat message history"""
    if not state.messages:
        st.chat_message("ai").write("Hello, how can I help you?")
    
    for message in state.messages:
        role = message.get("role")
        display_role = ""
        if role in ("human", "user"):
            display_role = "human"
        elif role in ("ai", "assistant"):
            if not message.get("content") and not message.get("tool_trace"):
                continue
            display_role = "assistant"
        else:
            continue
        
        with st.chat_message(display_role):
            if "tool_trace" in message and message["tool_trace"]:
                for tool_call in message["tool_trace"]:
                    with st.expander(f"🛠️ **Tool Call:** `{tool_call['name']}`", expanded=False):
                        st.text("Arguments:")
                        st.code(json.dumps(tool_call.get('args', {}), indent=2), language="json")
                        if "error" in tool_call:
                            st.text("Error:")
                            st.error(tool_call['error'])
                        else:
                            st.text("Result:")
                            st.code(tool_call.get('result', ''), language="json")
            if message.get("content"):
                # Display file attachments if present
                if "attachments" in message and message["attachments"]:
                    for file in message["attachments"]:
                        # Show appropriate icon based on file type
                        if file["type"].startswith("image/"):
                            cols = st.columns([1, 3])
                            with cols[0]:
                                st.image(file["preview"], use_container_width=True)
                        elif file["type"] == "application/pdf":
                            st.markdown(f"📄 **{file['name']}** ({file['size']//1024} KB)")
                        elif file["type"] in ("text/plain", "text/markdown"):
                            st.markdown(f"📝 **{file['name']}** ({file['size']//1024} KB)")
                        else:
                            st.markdown(f"📎 **{file['name']}** ({file['size']//1024} KB)")
                
                # Display message content - handle both string and list formats
                content = message.get("content")
                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            if "text" in part:
                                text_parts.append(part["text"])
                        elif isinstance(part, str):
                            text_parts.append(part)
                    st.markdown("\n".join(text_parts))
                else:
                    st.markdown(content)

def process_user_input(human_request):
    """Process user input including file attachments"""
    message = {"role": "user", "content": human_request.text}
    
    # Handle file attachments with base64 for display
    if hasattr(human_request, "files") and human_request.files:
        message["attachments"] = []
        for file in human_request.files:
            file_bytes = file.read()
            file_b64 = base64.b64encode(file_bytes).decode("utf-8")
            message["attachments"].append({
                "name": file.name,
                "type": file.type,
                "size": len(file_bytes),
                "data": file_b64,
                "preview": f"data:{file.type};base64,{file_b64}" if file.type.startswith("image/") else None
            })
    
    state.messages.append(message)

def prepare_client_settings():
    """Prepare client settings for MCPClient invocation"""
    client_settings_for_request = state.client_settings.copy()
    model_id = client_settings_for_request.get('ll_model', {}).get('model')
    if model_id:
        all_model_configs = st_common.enabled_models_lookup("ll")
        model_config = all_model_configs.get(model_id, {})
        if 'api_key' in model_config:
            if 'll_model' not in client_settings_for_request:
                client_settings_for_request['ll_model'] = {}
            client_settings_for_request['ll_model']['api_key'] = model_config['api_key']
    return client_settings_for_request

def prepare_message_history():
    """Process message history for backend"""
    message_history = []
    for msg in state.messages:
        processed_msg = msg.copy()
        
        if "attachments" in msg and msg["attachments"]:
            text_content = msg["content"]
            if isinstance(text_content, list):
                text_parts = []
                for part in text_content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        if "text" in part:
                            text_parts.append(part["text"])
                    elif isinstance(part, str):
                        text_parts.append(part)
                text_content = "\n".join(text_parts)
            
            content_list = [{"type": "text", "text": text_content}]
            for attachment in msg["attachments"]:
                if attachment["type"].startswith("image/"):
                    mime_type = attachment["type"]
                    if mime_type == "image/jpg":
                        mime_type = "image/jpeg"
                    content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{attachment['data']}",
                            "detail": "low"
                        }
                    })
                else:
                    # Handle non-image files as text references
                    content_list.append({
                        "type": "text",
                        "text": f"\n[File: {attachment['name']} ({attachment['size']//1024} KB)]"
                    })
            
            processed_msg["content"] = content_list
        # Convert list content to string format
        elif isinstance(msg.get("content"), list):
            text_parts = []
            for part in msg["content"]:
                if isinstance(part, dict) and part.get("type") == "text":
                    if "text" in part:
                        text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
            processed_msg["content"] = "\n".join(text_parts)
        # Otherwise, ensure content is a string
        else:
            processed_msg["content"] = str(msg.get("content", ""))
            
        message_history.append(processed_msg)
    return message_history

def process_final_text(final_text):
    """Convert final response text to string format"""
    if isinstance(final_text, list):
        text_parts = []
        for part in final_text:
            if isinstance(part, dict):
                part_type = part.get("type")
                part_text = part.get("text")
                if part_type == "text" and isinstance(part_text, str):
                    text_parts.append(part_text)
            elif isinstance(part, str):
                text_parts.append(part)
        return "\n".join(text_parts)
    return final_text

def find_last_user_message_index():
    """Find index of last user message in history"""
    last_user_idx = -1
    for i, msg in enumerate(state.messages):
        if msg.get("role") in ("human", "user"):
            last_user_idx = i
    return last_user_idx

def handle_invoke_error(e):
    """Handle exceptions during MCPClient invocation"""
    logger.error("Exception during invoke call:", exc_info=True)
    error_msg = str(e)
    
    if "file" in error_msg.lower() or "image" in error_msg.lower() or "content" in error_msg.lower():
        st.error(f"Error: {error_msg}")
        if st.button("Remove files and retry", key="remove_files_retry"):
            # Remove attachments from the latest message
            if state.messages and "attachments" in state.messages[-1]:
                del state.messages[-1]["attachments"]
            st.rerun()
    else:
        st.error(f"Error: {error_msg}")
    
    if st.button("Retry", key="reload_chatbot_error"):
        if state.messages and state.messages[-1]["role"] == "user":
            state.messages.pop()
        st.rerun()


#############################################################################
# MAIN
#############################################################################
async def main() -> None:
    """Streamlit GUI"""
    # Initialize critical session state variables
    if 'enable_client' not in state:
        state.enable_client = True
    if 'messages' not in state:
        state.messages = []
        # Add initial greeting message
        state.messages.append({
            "role": "assistant",
            "content": "Hello, how can I help you?"
        })
    
    try:
        get_models()
    except api_call.ApiError:
        st.stop()
    
    setup_sidebar()
    
    # Final safety check
    if not state.enable_client:
        st.stop()
    
    #########################################################################
    # Chatty-Bot Centre
    #########################################################################
    
    display_messages()
    sys_prompt = state.client_settings["prompts"]["sys"]
    render_chat_footer()
    
    if human_request := st.chat_input(
        f"Ask your question here... (current prompt: {sys_prompt})",
        accept_file=True,
        file_type=["jpg", "jpeg", "png", "pdf", "txt", "docx"],
        key=f"chat_input_{len(state.messages)}",
    ):
        process_user_input(human_request)
        st.rerun()
    
    if state.messages and state.messages[-1]["role"] == "user":
        try:
            with st.chat_message("ai"):
                with st.spinner("Thinking..."):
                    client_settings = prepare_client_settings()
                    message_history = prepare_message_history()
                    async with MCPClient(client_settings=client_settings) as mcp_client:
                        final_text, tool_trace, new_history = await mcp_client.invoke(
                            message_history=message_history
                        )
                    
                    final_text_str = process_final_text(final_text)
                    assistant_msg = {
                        "role": "assistant",
                        "content": final_text_str,
                        "tool_trace": tool_trace
                    }
                    
                    # Preserve attachments from user message
                    if "attachments" in state.messages[-1]:
                        assistant_msg["attachments"] = state.messages[-1]["attachments"]
                    
                    # Update or add assistant message
                    last_user_idx = find_last_user_message_index()
                    if last_user_idx + 1 < len(state.messages) and state.messages[last_user_idx + 1].get("role") == "assistant":
                        state.messages[last_user_idx + 1] = assistant_msg
                    else:
                        state.messages.append(assistant_msg)
                    
                    st.rerun()
        except Exception as e:
            handle_invoke_error(e)


if __name__ == "__main__" or ("page" in inspect.stack()[1].filename if inspect.stack() else False):
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
