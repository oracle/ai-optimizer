import inspect

from client.mcp.frontend import display_commands_tab, display_ide_tab, get_fastapi_base_url, get_server_capabilities

import streamlit as st

def main():
    fastapi_base_url = get_fastapi_base_url()
    tools, resources, prompts = get_server_capabilities(fastapi_base_url)
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    ide, commands = st.tabs(["🛠️ IDE", "📚 Available Commands"])

    with ide:
        # Display the IDE tab using the original AI Optimizer logic.
        display_ide_tab()
    with commands:
        # Display the commands tab using the original AI Optimizer logic.
        display_commands_tab(tools, resources, prompts)



if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
