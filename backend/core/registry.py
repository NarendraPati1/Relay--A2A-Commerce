from agents.merchant.config import MERCHANTS


MERCHANT_REGISTRY = [
    {
        "name": merchant["name"],
        "agent_url": f"http://127.0.0.1:{merchant['port']}",
    }
    for merchant in MERCHANTS.values()
]
