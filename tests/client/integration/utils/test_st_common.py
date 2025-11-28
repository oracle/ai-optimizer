# pylint: disable=protected-access,import-error,import-outside-toplevel,redefined-outer-name
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Note: Vector store selection tests have been moved to test_vs_options.py
following the refactor that moved vector store functionality from st_common.py
to vs_options.py.
"""
# spell-checker: disable

# This file previously contained integration tests for vector store selection
# functionality that was part of st_common.py. Those tests have been moved to:
#   tests/client/integration/utils/test_vs_options.py
#
# The st_common.py module no longer contains vector store selection functions.
# See vs_options.py for:
#   - vector_search_sidebar()
#   - vector_store_selection()
#   - Related helper functions (_get_vs_fields, _reset_selections, etc.)
