"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging
import time
import json
from typing import Optional, Dict
from urllib.parse import urljoin
import requests

import streamlit as st
from streamlit import session_state as state


LOGGER = logging.getLogger("client.utils.api_call")


class ApiError(Exception):
    """Custom Exception for API errors."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message.get("detail", str(message)) if isinstance(message, dict) else str(message)
        LOGGER.debug("ApiError: %s", self.message)

    def __str__(self):
        return self.message


def sanitize_sensitive_data(data):
    """Use to sanitize sensitive data for logging"""
    if isinstance(data, dict):
        return {
            k: "*****"
            if "password" in k.lower() or (isinstance(v, str) and "bearer" in v.lower())
            else sanitize_sensitive_data(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [sanitize_sensitive_data(i) for i in data]
    return data


def _handle_http_error(ex: requests.exceptions.HTTPError):
    """Extract error message from HTTP error response."""
    try:
        failure = ex.response.json().get("detail", "An error occurred.")
        if not failure and ex.response.status_code == 422:
            failure = "Not all required fields have been supplied."
    except (json.JSONDecodeError, ValueError, AttributeError):
        failure = f"HTTP {ex.response.status_code}: {ex.response.text[:200]}"
    return failure


def _error_response(message: str) -> None:
    """Display error to user and raise ApiError."""
    st.error(f"API Error: {message}")
    raise ApiError(message)


def send_request(
    method: str,
    endpoint: str,
    params: Optional[dict] = None,
    payload: Optional[Dict] = None,
    timeout: int = 60,
    retries: int = 3,
    backoff_factor: float = 2.0,
) -> dict:
    """Send API requests with retry logic. Returns JSON response or error dict."""
    method_map = {"GET": requests.get, "POST": requests.post, "PATCH": requests.patch, "DELETE": requests.delete}
    if method not in method_map:
        return _error_response(f"Unsupported HTTP method: {method}")

    url = urljoin(f"{state.server['url']}:{state.server['port']}/", endpoint)
    payload = payload or {}
    headers = {"Authorization": f"Bearer {state.server['key']}"}
    if getattr(state, "client_settings", {}).get("client"):
        headers["Client"] = state.client_settings["client"]

    args = {k: v for k, v in {
        "url": url,
        "headers": headers,
        "timeout": timeout,
        "params": params,
        "files": payload.get("files") if method == "POST" else None,
        "json": payload.get("json") if method in ["POST", "PATCH"] else None,
    }.items() if v is not None}

    log_args = sanitize_sensitive_data(args.copy())
    try:
        if log_args.get("files"):
            log_args["files"] = [(field_name, (f[0], "<binary_data>", f[2])) for field_name, f in log_args["files"]]
    except (ValueError, IndexError):
        pass
    LOGGER.info("%s Request: %s", method, log_args)

    result = None
    for attempt in range(retries + 1):
        try:
            response = method_map[method](**args)
            LOGGER.info("%s Response: %s", method, response)
            response.raise_for_status()
            result = response.json()
            LOGGER.debug("%s Data: %s", method, result)
            break

        except requests.exceptions.HTTPError as ex:
            LOGGER.error("HTTP Error: %s", ex)
            _error_response(_handle_http_error(ex))

        except requests.exceptions.ConnectionError as ex:
            LOGGER.error("Attempt %d: Connection Error: %s", attempt + 1, ex)
            if attempt < retries:
                time.sleep(backoff_factor * (2**attempt))
                continue
            _error_response(f"Connection failed after {retries + 1} attempts")

        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as ex:
            LOGGER.error("Request/JSON Error: %s", ex)
            _error_response(f"Request failed: {str(ex)}")

    return result if result is not None else _error_response("An unexpected error occurred.")


def get(endpoint: str, params: Optional[dict] = None, retries: int = 3, backoff_factor: float = 2.0) -> dict:
    """GET Requests"""
    return send_request("GET", endpoint, params=params, retries=retries, backoff_factor=backoff_factor)


def post(
    endpoint: str,
    params: Optional[dict] = None,
    payload: Optional[Dict] = None,
    timeout: int = 60,
    retries: int = 5,
    backoff_factor: float = 1.5,
) -> dict:
    """POST Requests"""
    return send_request(
        "POST",
        endpoint,
        params=params,
        payload=payload,
        timeout=timeout,
        retries=retries,
        backoff_factor=backoff_factor,
    )


def patch(
    endpoint: str,
    params: Optional[dict] = None,
    payload: Optional[dict] = None,
    timeout: int = 60,
    retries: int = 5,
    backoff_factor: float = 1.5,
    toast=True,
) -> dict:
    """PATCH Requests"""
    result = send_request(
        "PATCH",
        endpoint,
        params=params,
        payload=payload,
        timeout=timeout,
        retries=retries,
        backoff_factor=backoff_factor,
    )
    if toast:
        st.toast("Update Successful.", icon="✅")
        time.sleep(1)
    return result


def delete(endpoint: str, timeout: int = 60, retries: int = 5, backoff_factor: float = 1.5, toast=True) -> dict:
    """DELETE Requests"""
    result = send_request("DELETE", endpoint, timeout=timeout, retries=retries, backoff_factor=backoff_factor)
    if toast:
        st.toast(result.get("message", "Deleted."), icon="✅")
        time.sleep(1)
    return result
