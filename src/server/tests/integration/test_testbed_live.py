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


async def test_giskard_v3_generation_and_evaluation(live_oci_genai_models, live_oci_litellm_kwargs, tmp_path: Path):
    """Generate grounded questions and evaluate a Giskard v3 suite through OCI."""
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

    code = textwrap.dedent(
        """
        import asyncio
        import json
        import sys

        from server.app.api.v1.endpoints.testbed import _serialise_report
        from server.app.testbed.generation import generate_qa_records
        from server.app.testbed.metrics import build_evaluation_suite
        from llama_index.core.schema import TextNode

        config = json.load(sys.stdin)
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
        qa_records = asyncio.run(generate_qa_records(nodes, 2, config["chat"], config["embedding"]))
        assert len(qa_records) == 2
        assert all(record["question"] and record["reference_answer"] for record in qa_records)

        references = {record["question"]: record["reference_answer"] for record in qa_records}

        async def target(inputs):
            return {"answer": references[inputs["question"]]}

        suite = build_evaluation_suite(
            qa_records,
            target,
            config["chat"],
            "Compare the agent answer with the expected answer. Semantically equivalent answers are correct.",
        )
        result = asyncio.run(suite.run(verbose=False))
        payload = _serialise_report(result)
        assert len(payload["report"]["correctness"]) == 2
        assert payload["correctness"] == 1.0
        print("Live Giskard v3 generation and suite evaluation passed")
        """
    )
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
