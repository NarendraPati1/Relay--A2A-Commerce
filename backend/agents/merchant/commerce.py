from __future__ import annotations


class MerchantCommerceService:
    def __init__(
        self,
        merchant_id: str,
        merchant_name: str,
        inventory: dict,
        **_: object,
    ):
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.inventory = inventory

    def handle_request(self, request_text: str) -> str:
        product_name = self._find_product(request_text)

        if product_name is None:
            return f"{request_text} is not available."

        product = self.inventory[product_name]

        if product.get("stock", 0) <= 0:
            return f"{product_name} is not available."

        return (
            f"{product_name} is available. "
            f"Price: ₹{product['price']}. "
            f"Stock: {product['stock']}."
        )

    def _find_product(self, query: str) -> str | None:
        query_lower = query.lower()

        for product_name in self.inventory:
            if product_name.lower() in query_lower:
                return product_name

        query_tokens = {
            token
            for token in query_lower.replace(",", " ").split()
            if token
        }

        best_match = None
        best_score = 0

        for product_name in self.inventory:
            product_tokens = {
                token
                for token in product_name.lower().replace(",", " ").split()
                if token
            }
            score = len(query_tokens & product_tokens)

            if score > best_score:
                best_score = score
                best_match = product_name

        return best_match if best_score else None
