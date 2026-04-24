+++
title = 'API Examples'
weight = 30
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

The {{< short_app_ref >}} API Server exposes all features programmatically via REST endpoints. You can explore the full API reference through the built-in Swagger UI at `/v1/docs` when the server is running. The page prompts for the `x-api-key` on load before rendering the documentation.

All API requests require authentication using the `x-api-key` header, which must match the API key configured on the server.
