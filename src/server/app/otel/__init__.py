"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from server.app.otel.setup import init_telemetry, instrument_fastapi

__all__ = ["init_telemetry", "instrument_fastapi"]
