"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Load Giskard with the application's Bokeh-only report module.
"""

import sys
from importlib import import_module
from importlib.abc import MetaPathFinder
from importlib.metadata import version
from importlib.util import spec_from_file_location
from pathlib import Path

_REPORT_MODULE = "giskard.rag.report"
_REPORT_PATH = Path(__file__).with_name("giskard_rag_report.py")


class _ReportFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
        if fullname == _REPORT_MODULE:
            return spec_from_file_location(fullname, _REPORT_PATH)
        return None


def _load_rag() -> None:
    if version("giskard") != "2.19.2":
        raise ImportError("Review the local report patch before changing Giskard 2.19.2")
    loaded = sys.modules.get(_REPORT_MODULE)
    if loaded is not None and getattr(loaded, "__file__", None) != str(_REPORT_PATH):
        raise ImportError("Import server.patches.giskard before giskard.rag")

    finder = _ReportFinder()
    sys.meta_path.insert(0, finder)
    try:
        import_module("giskard.rag")
    finally:
        sys.meta_path.remove(finder)


_load_rag()

from giskard.rag import AgentAnswer, KnowledgeBase, QATestset, evaluate, generate_testset  # noqa: E402
from giskard.rag.question_generators import complex_questions, simple_questions  # noqa: E402
from giskard.rag.question_generators.utils import parse_json_output  # noqa: E402

__all__ = [
    "AgentAnswer",
    "KnowledgeBase",
    "QATestset",
    "complex_questions",
    "evaluate",
    "generate_testset",
    "parse_json_output",
    "simple_questions",
]
