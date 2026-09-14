import httpx

from a2a.client import A2ACardResolver
from a2a.client.client_factory import create_client
from a2a.types import (
    SendMessageRequest,
    Message,
    Part,
    Role,
)


MERCHANT_URL = "http://127.0.0.1:9000"


async def ask_merchant(query: str, merchant_url: str):

    async with httpx.AsyncClient() as httpx_client:

        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=merchant_url,
        )

        card = await resolver.get_agent_card()

        client = await create_client(card)

        message = Message(
            message_id="buyer-message",
            role=Role.ROLE_USER,
            parts=[
                Part(text=query)
            ],
        )

        request = SendMessageRequest(
            message=message
        )

        response_text = ""

        async for event in client.send_message(request):

            if event.task and event.task.artifacts:
                for artifact in event.task.artifacts:
                    for part in artifact.parts:
                        if part.text:
                            response_text = part.text

            elif event.message:
                for part in event.message.parts:
                    if part.text:
                        response_text = part.text

        return response_text


async def get_merchant_card(base_url: str):
    async with httpx.AsyncClient() as httpx_client:

        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url,
        )

        return await resolver.get_agent_card()