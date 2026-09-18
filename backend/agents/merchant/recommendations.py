"""Merchant-configured, optional cross-sell and upsell recommendations."""

from __future__ import annotations


class MerchantRecommendationPolicy:
    def __init__(self, inventory: dict, policy: dict | None = None):
        self.inventory = inventory
        self.policy = policy or {}

    def for_product(self, product_name: str) -> list[dict]:
        configured = self.policy.get(product_name, {})
        recommendations = []
        for kind in ("cross_sell", "upsell"):
            for candidate in configured.get(kind, []):
                item = self.inventory.get(candidate)
                if not item or item.get("stock", 0) <= 0:
                    continue
                recommendations.append({
                    "type": kind,
                    "product_name": candidate,
                    "unit_price": item["price"],
                })
        return recommendations
