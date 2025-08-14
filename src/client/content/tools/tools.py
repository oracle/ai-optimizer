"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
import inspect
import streamlit as st
from client.utils.st_common import style
from client.utils.st_footer import remove_footer

from client.content.tools.tabs.prompt_eng import display_prompt_eng
from client.content.tools.tabs.split_embed import display_split_embed

def main() -> None:
    """Streamlit GUI"""
    style()
    remove_footer()
    prompt_eng, split_embed = st.tabs(["🎤 Prompts", "📚 Split/Embed"])

    with prompt_eng:
        display_prompt_eng()
    with split_embed:
        display_split_embed()

if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()