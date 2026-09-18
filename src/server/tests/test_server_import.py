"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run_without_matplotlib(code: str, tmp_path: Path) -> None:
    src_root = Path(__file__).resolve().parents[2]
    prelude = """
from importlib.util import find_spec
assert find_spec("matplotlib") is None, "Run this test in an environment without matplotlib"
"""
    # Server conftest stubs Giskard; a subprocess exercises its actual imports.
    result = subprocess.run(
        [sys.executable, "-B", "-c", prelude + textwrap.dedent(code)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(src_root),
            "AIO_ENV": "pytest_import",
            "OTEL_TRACES_EXPORTER": "none",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_server_imports_without_matplotlib(tmp_path: Path):
    """Load the server with its installed dependencies in a fresh interpreter."""
    _run_without_matplotlib(
        """
        from uvicorn.importer import import_from_string
        assert callable(import_from_string("server.app.main:app"))
        """,
        tmp_path,
    )


def test_giskard_report_data_and_rendering_without_matplotlib(tmp_path: Path):
    """Exercise the installed Giskard testset and patched report together."""
    _run_without_matplotlib(
        """
        import sys
        from pathlib import Path

        from server.app.api.v1.endpoints.testbed import _serialise_report
        import server.patches
        from giskard.rag import AgentAnswer, QATestset, QuestionSample, RAGReport
        from giskard.rag.report import __file__ as report_path

        assert Path(report_path).parent == Path(server.patches.__file__).parent
        assert not any(type(finder).__module__ == "server.patches.giskard" for finder in sys.meta_path)
        samples = [
            QuestionSample(
                id=f"q{index}", question="What is the capital of France?",
                reference_answer="Paris", reference_context="Paris is the capital of France.",
                conversation_history=[], metadata={"topic": "Geography", "question_type": "simple"},
            )
            for index in range(2)
        ]
        testset = QATestset(samples)
        testset.save("questions.jsonl")
        testset = QATestset.load("questions.jsonl")
        report = RAGReport(
            testset, [AgentAnswer(message="Paris"), AgentAnswer(message="London")],
            {
                "q0": {"correctness": True, "correctness_reason": "", "relevance": 1.0},
                "q1": {"correctness": False, "correctness_reason": "Wrong capital", "relevance": 0.5},
            },
        )
        assert report.correctness == 0.5
        payload = _serialise_report(report)
        assert payload["report"]["agent_answer"] == {"q0": "Paris", "q1": "London"}
        assert payload["correct_by_topic"]["correctness"] == {"Geography": 0.5}
        assert payload["failures"]["correctness_reason"] == {"q1": "Wrong capital"}
        Path("saved-report").mkdir()
        report.save("saved-report")
        assert "Bokeh" in Path("saved-report/report.html").read_text()
        restored = RAGReport.load("saved-report")
        assert _serialise_report(restored) == payload
        assert "matplotlib" not in sys.modules
        """,
        tmp_path,
    )
