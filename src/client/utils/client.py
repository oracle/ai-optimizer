"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from typing import AsyncIterator
import httpx

from langchain_core.messages import ChatMessage
from common.schema import ChatRequest
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.utils.client")


class Client:
    """Client for interacting with the Server."""

    logger.debug("Initializing Client")

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

        def settings_request(method):
            """Send Settings to Server"""
            with httpx.Client() as client:
                return client.request(
                    method=method,
                    url=f"{self.server_url}/v1/settings",
                    json=self.settings,
                    **self.request_defaults,
                )

        response = settings_request("PATCH")
        if response.status_code != 200:
            logger.error("Error updating settings with PATCH: %i - %s", response.status_code, response.text)
            # Retry with POST if PATCH fails
            response = settings_request("POST")
            if response.status_code != 200:
                logger.error("Error updating settings with POST: %i - %s", response.status_code, response.text)
        logger.info("Established Client")

    async def stream(self, message: str) -> AsyncIterator[str]:
        """Call stream endpoint for completion"""
        # This is called by ChatBot, so enable streaming
        self.settings["ll_model"]["streaming"] = True
        request = ChatRequest(
            **self.settings["ll_model"],
            messages=[ChatMessage(role="human", content=message)],
        )
        logger.debug("Sending Request: %s", request.model_dump_json())
        client_call = {"json": request.model_dump(), **self.request_defaults}
        async with httpx.AsyncClient() as client:
            async with client.stream(
                method="POST", url=self.server_url + "/v1/chat/streams", **client_call
            ) as response:
                async for chunk in response.aiter_bytes():
                    content = chunk.decode("utf-8")
                    if content == "[stream_finished]":
                        break
                    yield content

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
