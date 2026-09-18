# Giskard report patch

`giskard_rag_report.py` is adapted from Giskard 2.19.2 under the license in
`LICENSE.giskard`. Its report plots use fixed Bokeh colors. The local copy removes
the matplotlib import, the `get_colors` helper, and the unused `colors` data column.

Testbed imports Giskard through `server.patches.giskard`. During the first RAG
import, this module loads the local report as `giskard.rag.report`. The import
finder is removed immediately afterward. The copy uses absolute Giskard imports
and follows the application's formatting and type-checking conventions.

When upgrading Giskard, compare the upstream report with this copy and update the
version check. Run `pytest src/server/tests/test_server_import.py` in an environment
without matplotlib.
