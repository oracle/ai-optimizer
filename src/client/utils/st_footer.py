"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit, selectbox, mult, iloc, selectai, isin

import streamlit.components.v1 as components

FOOTER_STYLE = """
<style>
    .footer-container, .footer {
        text-align: center !important;
    }
    .footer-container {
        padding-top: 0.5rem !important;
    }
    .footer {
        padding: 2rem 0 0.5rem 0 !important;
    }
    .footer-container p, .footer p {
        font-size: 12px !important;
        color: #8E8E93 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    .footer-container a, .footer a {
        color: #8E8E93 !important;
        text-decoration: underline !important;
    }
</style>
"""


# --- SHARED LOGIC ---
def _inject_footer(selector, insertion_method, footer_html, cleanup_styles=True):
    """
    Shared footer injection logic with optional style cleanup.

    Args:
        selector: CSS selector to find the injection target
        insertion_method: 'afterend' or 'beforebegin'
        footer_html: Complete HTML content to inject
        cleanup_styles: Whether to apply padding/margin cleanup to target element
    """
    js_safe_html = footer_html.replace("`", "\\`").replace("\n", "")
    cleanup_js = (
        """
            target.style.paddingBottom = '0';
            target.style.marginBottom = '0';"""
        if cleanup_styles
        else ""
    )
    js_code = f"""
    <script>
    const checkReady = setInterval(() => {{
        const target = parent.document.querySelector('{selector}');
        if (target && !parent.document.getElementById('page-footer')) {{
            clearInterval(checkReady);
            {cleanup_js}
            target.insertAdjacentHTML('{insertion_method}', `{js_safe_html}`);
        }}
    }}, 100);
    setTimeout(() => clearInterval(checkReady), 3000);
    </script>
    """
    components.html(js_code, height=0)

# --- The Chat Page Footer ---
def render_chat_footer():
    """
    Standardized footer for chat pages.
    """
    footer_html = f"""
    {FOOTER_STYLE}
    <div class="footer-container" id="page-footer">
        <p>LLMs can make mistakes. Always verify important information.</p>
    </div>
    """
    _inject_footer(
        selector='[data-testid="stBottomBlockContainer"]', insertion_method="afterend", footer_html=footer_html
    )
