"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import time
import json
from typing import Optional, Dict
from urllib.parse import urljoin
import requests

import streamlit as st
from streamlit import session_state as state
from common import logging_config

logger = logging_config.logging.getLogger("client.utils.api_call")


class ApiError(Exception):
    """Custom Exception for API errors."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message.get("detail", str(message)) if isinstance(message, dict) else str(message)
        logger.debug("ApiError: %s", self.message)

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


def send_request(
    method: str,
    endpoint: str,
    params: Optional[dict] = None,
    payload: Optional[Dict] = None,
    timeout: int = 60,
    retries: int = 3,
    backoff_factor: float = 2.0,
) -> dict:
    """Send API requests with retry logic."""
    url = urljoin(f"{state.server['url']}:{state.server['port']}/", endpoint)
    payload = payload or {}
    token = state.server["key"]
    headers = {"Authorization": f"Bearer {token}"}
    # Send client in header if it exists
    if getattr(state, "client_settings", {}).get("client"):
        headers["Client"] = state.client_settings["client"]

    method_map = {"GET": requests.get, "POST": requests.post, "PATCH": requests.patch, "DELETE": requests.delete}

    if method not in method_map:
        raise ApiError(f"Unsupported HTTP method: {method}")

    args = {
        "url": url,
        "headers": headers,
        "timeout": timeout,
        "params": params,
        "files": payload.get("files") if method == "POST" else None,
        "json": payload.get("json") if method in ["POST", "PATCH"] else None,
    }
    args = {k: v for k, v in args.items() if v is not None}
    # Avoid logging out binary data in files
    log_args = sanitize_sensitive_data(args.copy())
    try:
        if log_args.get("files"):
            log_args["files"] = [(field_name, (f[0], "<binary_data>", f[2])) for field_name, f in log_args["files"]]
    except (ValueError, IndexError):
        pass
    logger.info("%s Request: %s", method, log_args)
    for attempt in range(retries + 1):
        try:
            response = method_map[method](**args)
            data = response.json()
            logger.info("%s Response: %s", method, response)
            logger.debug("%s Data: %s", method, data)
            response.raise_for_status()
            return response

        except requests.exceptions.HTTPError as ex:
            logger.error(ex)
            failure = ex.response.json()["detail"]
            if not failure and ex.response.status_code == 422:
                failure = "Not all required fields have been supplied."
            raise ApiError(failure) from ex
        except requests.exceptions.RequestException as ex:
            logger.error("Attempt %d: Error: %s", attempt + 1, ex)
            if "HTTPConnectionPool" in str(ex):
                sleep_time = backoff_factor * (2**attempt)
                logger.info("Retrying in %.1f seconds...", sleep_time)
                time.sleep(sleep_time)
            if "Expecting value" in str(ex):
                raise ApiError("You've found a bug!  Please raise an issue.") from ex

    raise ApiError("An unexpected error occurred.")


def get(endpoint: str, params: Optional[dict] = None, retries: int = 3, backoff_factor: float = 2.0) -> json:
    """GET Requests"""
    response = send_request("GET", endpoint, params=params, retries=retries, backoff_factor=backoff_factor)
    return response.json()


def post(
    endpoint: str,
    params: Optional[dict] = None,
    payload: Optional[Dict] = None,
    timeout: int = 60,
    retries: int = 5,
    backoff_factor: float = 1.5,
) -> json:
    """POST Requests"""
    response = send_request(
        "POST",
        endpoint,
        params=params,
        payload=payload,
        timeout=timeout,
        retries=retries,
        backoff_factor=backoff_factor,
    )
    return response.json()


def patch(
    endpoint: str,
    params: Optional[dict] = None,
    payload: Optional[dict] = None,
    timeout: int = 60,
    retries: int = 5,
    backoff_factor: float = 1.5,
    toast=True,
) -> None:
    """PATCH Requests"""
    response = send_request(
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
    return response.json()


def delete(endpoint: str, timeout: int = 60, retries: int = 5, backoff_factor: float = 1.5, toast=True) -> None:
    """DELETE Requests"""
    response = send_request("DELETE", endpoint, timeout=timeout, retries=retries, backoff_factor=backoff_factor)
    success = response.json()["message"]
    if toast:
        st.toast(success, icon="✅")
