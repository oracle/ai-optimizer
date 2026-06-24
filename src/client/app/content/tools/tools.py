"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging

import streamlit as st
from streamlit import session_state as state

from client.app.content.tools.tabs.deepsec import display_deepsec
from client.app.content.tools.tabs.prompt_eng import display_prompt_eng
from client.app.content.tools.tabs.split_embed import display_split_embed

LOGGER = logging.getLogger("content.config.tools")


def main() -> None:
    """Streamlit GUI"""
    tab_labels = ["🎤 Prompts", "📚 Split/Embed", "🔒 Deep Data Security"]
    default_tab = tab_labels[0]
    if "tools_active_tab" not in state or state.tools_active_tab not in tab_labels:
        state.tools_active_tab = default_tab

    def _remember_active_tab() -> None:
        """Persist the current tab label so we can restore it later."""
        state.tools_active_tab = state.get("tools_tabs", default_tab)

    # Only create tabs if there is at least one
    if tab_labels:
        tabs = st.tabs(
            tab_labels,
            key="tools_tabs",
            default=state.tools_active_tab,
            on_change=_remember_active_tab,
        )
        _remember_active_tab()

        # Only render the active tab's body. ``st.tabs`` executes every
        # tab body on each rerun (inactive tabs are merely CSS-hidden), so
        # rendering all three would mount split/embed's run_every polling
        # fragment regardless of which tab is shown — polling embed/jobs
        # from the Prompts and Deep Data Security tabs too.
        if state.tools_active_tab == tab_labels[0]:
            with tabs[0]:
                display_prompt_eng()
        elif state.tools_active_tab == tab_labels[1]:
            with tabs[1]:
                display_split_embed()
        elif state.tools_active_tab == tab_labels[2]:
            with tabs[2]:
                display_deepsec()


if __name__ == "__main__":
    main()
