import streamlit as st
import os
import requests
import json

def set_page():
    st.set_page_config(
        page_title="MCP Universal Chatbot",
        page_icon="🤖",
        layout="wide"
    )

def get_fastapi_base_url():
    return os.getenv("FASTAPI_BASE_URL", "http://127.0.0.1:8000")

@st.cache_data(show_spinner="Connecting to MCP Backend...", ttl=60)
def get_server_capabilities(fastapi_base_url):
    """Fetches the lists of tools and resources from the FastAPI backend."""
    try:
        # Get API key from environment or generate one
        api_key = os.getenv("API_SERVER_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        
        # First check if MCP is enabled and initialized
        status_response = requests.get(f"{fastapi_base_url}/v1/mcp/status", headers=headers)
        if status_response.status_code == 200:
            status = status_response.json()
            if not status.get("enabled", False):
                st.warning("MCP is not enabled. Please enable it in the configuration.")
                return {"error": "MCP not enabled"}, {"error": "MCP not enabled"}, {"error": "MCP not enabled"}
            if not status.get("initialized", False):
                st.info("MCP is enabled but not yet initialized. Please select a model first.")
                return {"tools": []}, {"static": [], "dynamic": []}, {"prompts": []}
        
        tools_response = requests.get(f"{fastapi_base_url}/v1/mcp/tools", headers=headers)
        tools_response.raise_for_status()
        tools = tools_response.json()
        
        resources_response = requests.get(f"{fastapi_base_url}/v1/mcp/resources", headers=headers)
        resources_response.raise_for_status()
        resources = resources_response.json()

        prompts_response = requests.get(f"{fastapi_base_url}/v1/mcp/prompts", headers=headers)
        prompts_response.raise_for_status()
        prompts = prompts_response.json()
        
        return tools, resources, prompts
    except requests.exceptions.RequestException as e:
        st.error(f"Could not connect to the MCP backend at {fastapi_base_url}. Is it running? Error: {e}")
        return {"tools": []}, {"static": [], "dynamic": []}, {"prompts": []}

def get_server_files():
    files = ["server/mcp/server_config.json"]
    try:
        with open("server/mcp/server_config.json", "r") as f: config = json.load(f)
        for server in config.get("mcpServers", {}).values():
            script_path = server.get("args", [None])[0]
            if script_path and os.path.exists(script_path): files.append(script_path)
    except FileNotFoundError: st.sidebar.error("server_config.json not found!")
    return list(set(files))

def display_ide_tab():
    st.header("🔧 Integrated MCP Server IDE")
    st.info("Edit your server configuration or scripts. Restart the launcher for changes to take effect.")
    server_files = get_server_files()
    selected_file = st.selectbox("Select a file to edit", options=server_files)
    if selected_file:
        with open(selected_file, "r") as f: file_content = f.read()
        from streamlit_ace import st_ace
        new_content = st_ace(value=file_content, language="python" if selected_file.endswith(".py") else "json", theme="monokai", keybinding="vscode", height=500, auto_update=True)
        if st.button("Save Changes"):
            with open(selected_file, "w") as f: f.write(new_content)
            st.success(f"Successfully saved {selected_file}!")

def display_commands_tab(tools, resources, prompts):
    st.header("📖 Discovered MCP Commands")
    st.info("These commands were discovered from the MCP backend.")
    
    if tools:
        with st.expander("🛠️ Available Tools (Used automatically by the AI)", expanded=True):
            # Extract just the tool names from the tools response
            if "tools" in tools and isinstance(tools["tools"], list):
                tool_names = [tool.get("name", tool) if isinstance(tool, dict) else tool for tool in tools["tools"]]
                st.write(tool_names)
            else:
                st.json(tools)
    
    if resources:
        with st.expander("📦 Available Resources (Use with `@<name>` or just `<name>`)"):
            st.json(resources)
    
    if prompts:
        with st.expander("📝 Available Prompts (Use with `/prompt <name>` or select in chat)"):
            st.json(prompts)
