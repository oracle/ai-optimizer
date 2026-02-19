"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from typing import AsyncIterator, Optional
import time
import httpx

from langchain_core.messages import ChatMessage
from common.schema import ChatRequest
from common import logging_config

logger = logging_config.logging.getLogger("client.utils.client")


class Client:
    """Client for interacting with the Chatbot."""

    logger.debug("Initializing Chatbot Client")

    def __init__(
        self,
        server: dict,
        settings: dict,
        agent: str = "chatbot",
        timeout: float | None = None,
    ) -> None:
        """Initialize the client."""
        self.server_url = f"{server['url']}:{server['port']}"
        self.settings = settings
        self.agent = agent

        self.request_defaults = {
            "headers": {
                "Authorization": f"Bearer {server['key']}",
                "Client": self.settings["client"],
                "Content-Type": "application/json",
            },
            "params": {"client": self.settings["client"]},
            "timeout": timeout,
        }

        def settings_request(method, max_retries=3, backoff_factor=0.5):
            """Send Settings to Server with retry on failure"""
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    with httpx.Client() as client:
                        return client.request(
                            method=method,
                            url=f"{self.server_url}/v1/settings",
                            json=self.settings,
                            **self.request_defaults,
                        )
                except httpx.HTTPError as ex:
                    last_exception = ex
                    logger.error("Failed settings request %i: %s", attempt, ex)
                    if attempt < max_retries:
                        sleep_time = backoff_factor * (2 ** (attempt - 1))  # Exponential backoff
                        time.sleep(sleep_time)
            # All retries exhausted, raise the last exception
            raise last_exception

        response = settings_request("PATCH")
        if response.status_code != 200:
            logger.error("Error updating settings with PATCH: %i - %s", response.status_code, response.text)
            # Retry with POST if PATCH fails
            response = settings_request("POST")
            if response.status_code != 200:
                logger.error("Error updating settings with POST: %i - %s", response.status_code, response.text)
        logger.info("Established Chatbot Client: %s", self.settings["client"])

    async def stream(self, message: str, image_b64: Optional[str] = None) -> AsyncIterator[str]:
        """Call stream endpoint for completion"""
        if image_b64:
            content = [
                {"type": "text", "text": message},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]
        else:
            content = message

        request = ChatRequest(
            **self.settings["ll_model"],
            messages=[ChatMessage(role="human", content=content)],
        )
        logger.debug("Sending Request: %s", request.model_dump_json())
        client_call = {"json": request.model_dump(), **self.request_defaults}
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    method="POST", url=self.server_url + "/v1/chat/streams", **client_call
                ) as response:
                    async for chunk in response.aiter_bytes():
                        content = chunk.decode("utf-8")
                        if content == "[stream_finished]":
                            break
                        yield content
        except httpx.HTTPError as ex:
            logger.exception("HTTP error during streaming: %s", ex)
            raise ConnectionError(f"Streaming connection failed: {ex}") from ex

    async def get_history(self) -> list[ChatMessage]:
        """Output all chat history"""
        try:
            response = httpx.get(
                url=self.server_url + "/v1/chat/history",
                **self.request_defaults,
            )
            response_data = response.json()
            logger.debug("Response Received: %s", response_data)
            if response.status_code == 200:
                return response_data

            error_msg = response_data["detail"][0].get("msg", response.text)
            return f"Error: {response.status_code} - {error_msg}"
        except httpx.ConnectError:
            logger.error("Unable to contact the API Server; will try again later.")
