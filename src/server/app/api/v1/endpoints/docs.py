"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Swagger UI gate page and authenticated OpenAPI schema endpoint.

These replace FastAPI's built-in `docs_url` / `openapi_url` routes so the
OpenAPI schema can only be fetched with a valid X-API-Key, while the Swagger
UI HTML shell remains reachable from a normal browser address bar.
"""
# spell-checker:ignore jsdelivr noauth preauthorize

import html
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

noauth = APIRouter()
auth = APIRouter()

_SWAGGER_CSS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
_SWAGGER_JS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"


@auth.get("/openapi.json", include_in_schema=False)
async def openapi_schema(request: Request) -> JSONResponse:
    """Return the OpenAPI schema, injecting root_path into servers.

    Mirrors FastAPI's built-in /openapi.json behavior so Swagger UI and
    generated clients target the correct base URL when deployed behind a
    prefix (AIO_SERVER_URL_PREFIX). The cached app schema is not mutated.
    """
    schema: dict[str, Any] = request.app.openapi()
    root_path = request.scope.get("root_path", "").rstrip("/")
    if root_path:
        servers = schema.get("servers", [])
        if not any(s.get("url") == root_path for s in servers):
            schema = {**schema, "servers": [{"url": root_path}, *servers]}
    return JSONResponse(schema)


@noauth.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui(request: Request) -> HTMLResponse:
    """Serve a Swagger UI gate page.

    The HTML shell is public and contains no schema data. The user enters an
    API key; the page then fetches `./openapi.json` (resolves correctly under
    a root_path) with the key, and initializes Swagger UI with the returned
    spec. `preauthorizeApiKey` is called so "Try it out" requests reuse the
    same key without a second entry in the built-in Authorize dialog.
    """
    title = html.escape(f"{request.app.title} - Swagger UI")
    page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="{_SWAGGER_CSS}">
  <style>
    body {{ margin: 0; font-family: sans-serif; }}
    #gate {{ padding: 2em; max-width: 480px; }}
    #gate input {{ width: 100%; padding: 0.5em; font-size: 1em; box-sizing: border-box; }}
    #gate button {{ margin-top: 0.5em; padding: 0.5em 1em; font-size: 1em; cursor: pointer; }}
    #gate-error {{ color: #c00; margin-top: 0.5em; min-height: 1em; }}
  </style>
</head>
<body>
  <div id="gate">
    <h2>{title}</h2>
    <p>Enter your API key to load the documentation.</p>
    <label for="api-key">X-API-Key</label>
    <input id="api-key" type="password" autocomplete="off" autofocus>
    <button id="api-key-submit" type="button">Load</button>
    <div id="gate-error" role="alert"></div>
  </div>
  <div id="swagger-ui"></div>
  <script src="{_SWAGGER_JS}"></script>
  <script>
    (function () {{
      const keyInput = document.getElementById('api-key');
      const button = document.getElementById('api-key-submit');
      const errorBox = document.getElementById('gate-error');
      const gate = document.getElementById('gate');

      async function loadDocs() {{
        errorBox.textContent = '';
        const key = keyInput.value.trim();
        if (!key) {{
          errorBox.textContent = 'API key is required.';
          return;
        }}
        try {{
          const resp = await fetch('./openapi.json', {{ headers: {{ 'X-API-Key': key }} }});
          if (resp.status === 403) {{
            errorBox.textContent = 'Invalid API key.';
            return;
          }}
          if (!resp.ok) {{
            errorBox.textContent = 'Failed to load spec: HTTP ' + resp.status;
            return;
          }}
          const spec = await resp.json();
          gate.style.display = 'none';
          window.ui = SwaggerUIBundle({{
            spec: spec,
            dom_id: '#swagger-ui',
            deepLinking: true,
            presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
            layout: 'BaseLayout'
          }});
          window.ui.preauthorizeApiKey('APIKeyHeader', key);
        }} catch (err) {{
          errorBox.textContent = 'Failed to load spec: ' + err;
        }}
      }}

      button.addEventListener('click', loadDocs);
      keyInput.addEventListener('keydown', function (e) {{
        if (e.key === 'Enter') {{ loadDocs(); }}
      }});
    }})();
  </script>
</body>
</html>"""
    return HTMLResponse(content=page)
