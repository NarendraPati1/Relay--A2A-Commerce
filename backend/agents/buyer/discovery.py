import asyncio

from agents.buyer.a2a_client import get_merchant_card
from core.registry import MERCHANT_REGISTRY


async def discover_merchants():
    async def discover_one(merchant: dict):
        try:
            card = await get_merchant_card(merchant["agent_url"])

            return {
                "name": card.name,
                "description": card.description,
                "url": merchant["agent_url"],
                "agent_url": merchant["agent_url"],
                "skills": [
                    skill.name
                    for skill in getattr(card, "skills", [])
                ],
                "status": "available",
            }

        except Exception as exc:
            print(
                f"Discovery failed for {merchant['name']}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    results = await asyncio.gather(
        *(discover_one(merchant) for merchant in MERCHANT_REGISTRY)
    )
    return [merchant for merchant in results if merchant is not None]
