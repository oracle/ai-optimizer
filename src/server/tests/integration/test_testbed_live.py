"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import asyncio
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = [pytest.mark.live_oci, pytest.mark.integration]


async def test_giskard_generation_and_evaluation_without_matplotlib(
    live_oci_genai_models, live_oci_litellm_kwargs, tmp_path: Path
):
    """Generate and judge real questions through OCI in a fresh, unmocked process."""
    models = [model for model in live_oci_genai_models if model.get("region") == os.environ["AIO_GENAI_REGION"]]
    chat_models = sorted(
        model["model_name"]
        for model in models
        if (model.get("vendor") or "").lower() == "google" and "CHAT" in (model.get("capabilities") or [])
    )
    embedding_models = sorted(
        model["model_name"]
        for model in models
        if (model.get("vendor") or "").lower() == "cohere" and "TEXT_EMBEDDINGS" in (model.get("capabilities") or [])
    )
    if not chat_models or not embedding_models:
        pytest.skip("Requires Google CHAT and Cohere TEXT_EMBEDDINGS models in the configured OCI region")

    code = textwrap.dedent("""
        import asyncio
        import json
        import sys
        from importlib.util import find_spec
        from pathlib import Path

        assert find_spec("matplotlib") is None, "Run this test in an environment without matplotlib"
        from server.app.api.v1.endpoints.testbed import _run_giskard_evaluation, _serialise_report
        from server.app.testbed.generation import build_knowledge_base, get_giskard_config
        from server.patches.giskard import AgentAnswer, QATestset
        from llama_index.core.schema import TextNode

        config = json.load(sys.stdin)
        ll_config = get_giskard_config(config["chat"], "ll")
        embed_config = get_giskard_config(config["embedding"], "embed")
        destinations = [
            ("France", "Paris", "French", "Eiffel Tower"),
            ("Italy", "Rome", "Italian", "Colosseum"),
            ("Spain", "Madrid", "Spanish", "Prado Museum"),
            ("Portugal", "Lisbon", "Portuguese", "Belem Tower"),
            ("Germany", "Berlin", "German", "Brandenburg Gate"),
            ("Austria", "Vienna", "German", "Schonbrunn Palace"),
            ("Greece", "Athens", "Greek", "Acropolis"),
            ("Norway", "Oslo", "Norwegian", "Vigeland Park"),
            ("Denmark", "Copenhagen", "Danish", "Little Mermaid statue"),
            ("Finland", "Helsinki", "Finnish", "Helsinki Cathedral"),
            ("Sweden", "Stockholm", "Swedish", "Vasa Museum"),
            ("Poland", "Warsaw", "Polish", "Royal Castle"),
        ]
        nodes = [
            TextNode(text=f"The capital of {country} is {capital}. A primary language is {language}. "
                          f"Visitors to {capital} can see the {landmark}.")
            for country, capital, language, landmark in destinations
        ]
        testset = build_knowledge_base(nodes, 2, ll_config, embed_config)
        assert len(testset) == 2
        assert set(testset.get_metadata_values("question_type")) == {"simple", "complex"}
        assert all(sample.question and sample.reference_answer for sample in testset.samples)
        testset.save("generated.jsonl")
        restored = QATestset.load("generated.jsonl")
        answers = [AgentAnswer(message=sample.reference_answer) for sample in restored.samples]
        report = asyncio.run(_run_giskard_evaluation(
            restored, answers, ll_config,
            "Compare the agent answer to the expected answer. Equivalent answers are correct.",
        ))
        payload = _serialise_report(report)
        assert len(payload["report"]["correctness"]) == 2
        assert all(value is True for value in payload["report"]["correctness"].values())
        assert report.correctness == 1.0
        report.save("live-report")
        assert "Bokeh" in Path("live-report/report.html").read_text()
        assert "matplotlib" not in sys.modules
        print("Live Giskard generation, evaluation, serialization and rendering passed")
    """)
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-B", "-c", code],
        input=json.dumps(
            {
                "chat": {"model": f"oci/{chat_models[0]}", **live_oci_litellm_kwargs},
                "embedding": {"model": f"oci/{embedding_models[0]}", **live_oci_litellm_kwargs},
            }
        ),
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
            "AIO_ENV": "pytest_import",
            "OTEL_TRACES_EXPORTER": "none",
        },
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
