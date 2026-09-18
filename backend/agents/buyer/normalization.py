import re

from agents.buyer.llm import offer_normalizer_llm


def _deterministic_offer(offer: dict) -> dict | None:
    """Parse the merchant protocol's canonical offer without an LLM call."""
    response = str(offer.get("response", ""))
    product = offer.get("product") or {}
    price = re.search(r"(?:price|final unit price)\s*:\s*[₹Rs.INR ]*([0-9]+(?:\.[0-9]+)?)", response, re.I)
    stock = re.search(r"stock\s*:\s*(\d+)", response, re.I)

    if "not available" in response.lower() or "out of stock" in response.lower():
        return {
            "merchant": offer.get("merchant"), "merchant_url": offer.get("merchant_url"),
            "product_id": product.get("id"), "product_name": product.get("name", ""),
            "available": False, "price": None, "stock": 0, "currency": "INR",
            "pack_size": product.get("pack_size"), "offer_notes": [], "product": product,
            "raw_response": response, "item_query": offer.get("item_query"),
        }

    # The A2A reply must describe the exact catalog candidate we asked about.
    # A merchant may recommend a different SKU, but it cannot be silently
    # relabelled as the requested product; substitution is a separate flow.
    product_match = re.search(r"^\s*(.+?)\s+is\s+available\.", response, re.I)
    if product_match and product_match.group(1).strip().casefold() != str(product.get("name", "")).strip().casefold():
        return {
            "merchant": offer.get("merchant"), "merchant_url": offer.get("merchant_url"),
            "product_id": product.get("id"), "product_name": product.get("name", ""),
            "available": False, "price": None, "stock": 0, "currency": "INR",
            "pack_size": product.get("pack_size"),
            "offer_notes": ["merchant_returned_different_product"], "product": product,
            "raw_response": response, "item_query": offer.get("item_query"),
        }
    if not (price and stock):
        return None
    return {
        "merchant": offer.get("merchant"), "merchant_url": offer.get("merchant_url"),
        "product_id": product.get("id"), "product_name": product.get("name", ""),
        "available": True, "price": float(price.group(1)), "stock": int(stock.group(1)),
        "currency": "INR", "pack_size": product.get("pack_size"), "offer_notes": [],
        "product": product, "raw_response": response, "item_query": offer.get("item_query"),
    }


def normalize_offers(merchant_offers: list[dict]) -> list[dict]:
    normalized: list[dict] = []

    for offer in merchant_offers:
        product = offer.get("product") or {}
        product_name = product.get("name", "")
        deterministic = _deterministic_offer(offer)
        if deterministic is not None:
            normalized.append(deterministic)
            continue

        try:
            result = offer_normalizer_llm.invoke({
                "merchant": offer.get("merchant", ""),
                "product_name": product_name,
                "response": offer.get("response", ""),
            })

            normalized.append({
                "merchant": result.merchant or offer.get("merchant"),
                "merchant_url": offer.get("merchant_url"),
                "product_id": product.get("id"),
                "product_name": result.product_name or product_name,
                "available": bool(result.available),
                "price": result.price,
                "stock": result.stock,
                "currency": result.currency or "INR",
                "pack_size": result.pack_size or product.get("pack_size"),
                "offer_notes": result.offer_notes,
                "product": product,
                "raw_response": offer.get("response", ""),
                "item_query": offer.get("item_query"),
            })

        except Exception as exc:
            # Keep the raw offer visible but never invent normalized values.
            normalized.append({
                "merchant": offer.get("merchant"),
                "merchant_url": offer.get("merchant_url"),
                "product_id": product.get("id"),
                "product_name": product_name,
                "available": False,
                "price": None,
                "stock": None,
                "currency": "INR",
                "pack_size": product.get("pack_size"),
                "offer_notes": [f"normalization_failed: {type(exc).__name__}"],
                "product": product,
                "raw_response": offer.get("response", ""),
                "item_query": offer.get("item_query"),
            })

    return normalized
