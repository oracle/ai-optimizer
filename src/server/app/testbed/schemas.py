"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Domain identities and shared shapes for the testbed feature.
"""
# spell-checker: ignore testset testsets

from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field

HEX_RAW_ID_PATTERN = r"^[0-9a-fA-F]{32}$"

TestsetId = Annotated[
    str,
    Field(pattern=HEX_RAW_ID_PATTERN, description="Testset ID as a 32-character hex string."),
]
EvalId = Annotated[
    str,
    Field(pattern=HEX_RAW_ID_PATTERN, description="Evaluation ID as a 32-character hex string."),
]

# aio_testsets.name is VARCHAR2(255) NOT NULL — bound the input to match the column.
TestsetName = Annotated[
    str,
    Field(min_length=1, max_length=255, description="Human-readable testset name."),
]
QuestionCount = Annotated[
    int,
    Field(ge=1, description="Number of questions to generate (>= 1)."),
]


class QARecord(BaseModel):
    """One saved question, its reference answer, and optional context."""

    model_config = {"extra": "forbid"}

    id: str
    question: str
    reference_answer: str
    reference_context: str
    conversation_history: list[dict[str, str]]
    metadata: dict[str, Any]
    agent_answer: Optional[str] = None
    correctness: Optional[bool] = None


class RAGReportPayload(BaseModel):
    """Shape of a Testbed evaluation report persisted in aio_evaluations.rag_report.

    Each field is a dict produced by ``DataFrame.to_json()`` — keys are column
    names, values are nested ``{index: cell}`` dicts. Field-level defaults
    preserve compatibility with legacy rows that may be missing some keys.
    """

    report: dict[str, Any] = Field(default_factory=dict)
    correct_by_topic: dict[str, Any] = Field(default_factory=dict)
    failures: dict[str, Any] = Field(default_factory=dict)
    quality_metrics: dict[str, float | None] = Field(default_factory=dict)
