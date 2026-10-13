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


def _run_in_subprocess(code: str, tmp_path: Path) -> None:
    src_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(code)],
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


def test_server_imports_with_giskard_v3(tmp_path: Path):
    """Load the server and the installed Giskard Checks API in a fresh interpreter."""
    _run_in_subprocess(
        """
        from uvicorn.importer import import_from_string
        from giskard.checks import Check, Scenario, Suite

        assert callable(import_from_string("server.app.main:app"))
        assert Check is not None and Scenario is not None and Suite is not None
        """,
        tmp_path,
    )


def test_giskard_suite_report_serialization(tmp_path: Path):
    """Translate v3 suite results into the stored Testbed report format."""
    _run_in_subprocess(
        """
        import asyncio

        from giskard.checks import Scenario, StringMatching, Suite
        from server.app.api.v1.endpoints.testbed import _serialise_report

        suite = Suite(name="Testbed")
        for question, answer in (("Capital of France?", "Paris"), ("Capital of Italy?", "Milan")):
            scenario = (
                Scenario(name=question)
                .interact(
                    inputs={"question": question},
                    outputs={"answer": answer},
                    metadata={
                        "id": question,
                        "reference_answer": "Paris",
                        "reference_context": "Paris is the capital of France.",
                        "conversation_history": [],
                        "metadata": {"topic": "Geography"},
                    },
                )
                .check(StringMatching(keyword="Paris", target_key="trace.last.outputs.answer"))
            )
            suite.append(scenario)

        result = asyncio.run(suite.run(verbose=False))
        payload = _serialise_report(result)
        assert payload["correctness"] == 0.5
        assert payload["correct_by_topic"]["correctness"]["Geography"] == 0.5
        assert payload["report"]["agent_answer"]["Capital of France?"] == "Paris"
        assert payload["failures"]["agent_answer"]["Capital of Italy?"] == "Milan"
        """,
        tmp_path,
    )
