"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for testbed API request and response schemas.
"""
# spell-checker: ignore testset testsets

from typing import Any

from pydantic import BaseModel, Field


class QASets(BaseModel):
    """Testset metadata — maps to aio_testsets rows."""

    tid: str = Field(description="Testset ID (hex)")
    name: str = Field(description="Name of QA Set")
    created: str = Field(description="Date QA Set was loaded")


class RejectedFile(BaseModel):
    """A PDF that was skipped during testset generation."""

    filename: str = Field(description="Original filename of the rejected PDF")
    reason: str = Field(description="Why the file was rejected")


class QASetData(BaseModel):
    """Q&A data container for a testset."""

    qa_data: list[str | dict[str, Any]] = Field(description="QA Set Data (list of QA objects)")
    rejected_files: list[RejectedFile] = Field(
        default_factory=list, description="Files skipped during generation with reasons"
    )


class Evaluation(BaseModel):
    """Evaluation summary record."""

    eid: str = Field(description="Evaluation ID (hex)")
    evaluated: str = Field(description="Date of Evaluation")
    correctness: float = Field(description="Correctness score")


class EvaluationReport(Evaluation):
    """Full evaluation report with details."""

    settings: dict[str, Any] = Field(description="Settings snapshot used for evaluation")
    report: dict[str, Any] = Field(description="Full report")
    correct_by_topic: dict[str, Any] = Field(description="Correctness breakdown by topic")
    failures: dict[str, Any] = Field(description="Failure details")
    html_report: str = Field(description="HTML formatted report")
