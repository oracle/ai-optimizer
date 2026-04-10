"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Response models for probe endpoints.
"""

from pydantic import BaseModel


class ProbeResponse(BaseModel):
    """Response for liveness and readiness probes."""

    status: str


class StatusResponse(BaseModel):
    """Response for the authenticated status endpoint."""

    version: str
    status: str
