from agents.buyer.llm import offer_normalizer_llm


def normalize_offers(
    merchant_offers: list[dict],
) -> list[dict]:

    normalized_offers = []

    for offer in merchant_offers:

        result = offer_normalizer_llm.invoke({
            "merchant": offer["merchant"],
            "product_name": offer["product"]["name"],
            "response": offer["response"],
        })

        normalized_offers.append({
            "merchant": result.merchant,
            "merchant_url": offer["merchant_url"],
            "product_id": offer["product"]["id"],
            "product_name": result.product_name,
            "available": result.available,
            "price": result.price,
            "stock": result.stock,
            "currency": result.currency,
            "raw_response": offer["response"],
        })

    return normalized_offers