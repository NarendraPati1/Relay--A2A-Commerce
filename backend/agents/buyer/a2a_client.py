import asyncio
import os
import uuid
import httpx

from a2a.client import A2ACardResolver
from a2a.client.client_factory import create_client
from a2a.types import SendMessageRequest, Message, Part, Role


# Tunable operational limits: unavailable merchants must not hold an entire
# buyer turn hostage. Production values belong in deployment configuration.
DEFAULT_TIMEOUT = float(os.getenv("A2A_TIMEOUT_SECONDS", "5"))
MAX_RETRIES = int(os.getenv("A2A_MAX_RETRIES", "1"))
MAX_MERCHANT_RESPONSE_CHARS = int(
    os.getenv("A2A_MAX_MERCHANT_RESPONSE_CHARS", "4000")
)


async def get_merchant_card(base_url: str):
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as httpx_client:
                resolver = A2ACardResolver(
                    httpx_client=httpx_client,
                    base_url=base_url,
                )
                return await resolver.get_agent_card()
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))

    raise RuntimeError(
        f"Unable to retrieve merchant agent card from {base_url}: "
        f"{type(last_error).__name__}: {last_error}"
    )


async def ask_merchant(query: str, merchant_url: str) -> str:
    """
    Robust A2A request:
    - fresh message id per request
    - timeout
    - retry on transient failures
    - collects all textual artifact/message parts
    """
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as httpx_client:
                resolver = A2ACardResolver(
                    httpx_client=httpx_client,
                    base_url=merchant_url,
                )

                card = await resolver.get_agent_card()
                client = await create_client(card)

                message = Message(
                    message_id=str(uuid.uuid4()),
                    role=Role.ROLE_USER,
                    parts=[Part(text=query)],
                )

                request = SendMessageRequest(message=message)

                chunks: list[str] = []
                received_chars = 0

                async for event in client.send_message(request):
                    if event.task and event.task.artifacts:
                        for artifact in event.task.artifacts:
                            for part in artifact.parts:
                                if getattr(part, "text", None):
                                    remaining = MAX_MERCHANT_RESPONSE_CHARS - received_chars
                                    if remaining > 0:
                                        text = part.text[:remaining]
                                        chunks.append(text)
                                        received_chars += len(text)

                    if event.message:
                        for part in event.message.parts:
                            if getattr(part, "text", None):
                                remaining = MAX_MERCHANT_RESPONSE_CHARS - received_chars
                                if remaining > 0:
                                    text = part.text[:remaining]
                                    chunks.append(text)
                                    received_chars += len(text)

                response = "\n".join(
                    dict.fromkeys(
                        chunk.strip()
                        for chunk in chunks
                        if chunk and chunk.strip()
                    )
                )

                if not response:
                    return "Merchant returned no textual offer."

                return response[:MAX_MERCHANT_RESPONSE_CHARS]

        except (httpx.TimeoutException, httpx.NetworkError, Exception) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))

    return (
        f"A2A merchant request failed after retries: "
        f"{type(last_error).__name__}: {last_error}"
    )
