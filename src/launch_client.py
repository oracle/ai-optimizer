"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import os
import sys

msg = (
    "\n"
    "╔══════════════════════════════════════════════════════════════════╗\n"
    "║  DEPRECATED: launch_client.py is no longer supported.            ║\n"
    "║                                                                  ║\n"
    "║  Please use:  python entrypoint.py client                        ║\n"
    "╚══════════════════════════════════════════════════════════════════╝\n"
)

print(msg, file=sys.stderr)

# When invoked via `streamlit run`, sys.exit() is caught by Streamlit.
# Force-kill the process to prevent Streamlit from starting.
os._exit(1)
