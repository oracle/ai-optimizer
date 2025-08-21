"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import inspect
import streamlit as st

from client.content.tools.tabs.prompt_eng import get_prompts, display_prompt_eng
from client.content.tools.tabs.split_embed import display_split_embed
from client.content.config.tabs.models import get_models
from client.content.config.tabs.databases import get_databases
from client.content.config.tabs.oci import get_oci


def main() -> None:
    """Streamlit GUI"""
    prompt_eng, split_embed = st.tabs(["🎤 Prompts", "📚 Split/Embed"])

    with prompt_eng:
        get_prompts()
        display_prompt_eng()
    with split_embed:
        get_models()
        get_databases()
        get_oci()
        display_split_embed()


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
