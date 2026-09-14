from agents.buyer.a2a_client import get_merchant_card
from core.registry import MERCHANT_REGISTRY


async def discover_merchants():
    merchants = []

    print("Registry:", MERCHANT_REGISTRY)

    for merchant in MERCHANT_REGISTRY:
        print(f"Discovering: {merchant['name']}")

        try:
            card = await get_merchant_card(
                merchant["agent_url"]
            )

            print(f"Discovered: {card.name}")

            merchants.append({
                "name": card.name,
                "description": card.description,
                "url": merchant["agent_url"],
                "skills": [
                    skill.name
                    for skill in card.skills
                ],
            })

        except Exception as e:
            print(
                f"Discovery failed for "
                f"{merchant['name']}: {type(e).__name__}: {e}"
            )

    return merchants