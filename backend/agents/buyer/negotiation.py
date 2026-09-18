import re

from agents.buyer.a2a_client import ask_merchant


def decide_negotiation(
    user_query: str,
    shopping_goal: dict,
    selected_offer: dict,
):
    quantity = (
        selected_offer.get("effective_quantity")
        or selected_offer.get("required_quantity")
        or shopping_goal.get("quantity")
        or 1
    )
    asks_for_price = any(
        phrase in user_query.lower()
        for phrase in ("discount", "negotiate", "best price", "better price", "deal")
    )
    should_negotiate = bool(
        asks_for_price or shopping_goal.get("budget") is not None or quantity >= 3
    )

    return {
        "negotiation_requested": should_negotiate,
        "negotiation_reasoning": (
            "Customer requested a better price."
            if asks_for_price
            else "Quantity or budget makes a bulk-price inquiry worthwhile."
            if should_negotiate
            else "No quantity, budget, or price request justifies negotiation."
        ),
    }


async def negotiate_offer(
    selected_offer: dict,
    shopping_goal: dict,
):
    merchant_url = selected_offer.get("merchant_url")
    current_price = selected_offer.get("price")
    product_name = selected_offer.get("product_name")
    quantity = (
        selected_offer.get("effective_quantity")
        or selected_offer.get("required_quantity")
        or shopping_goal.get("quantity")
        or 1
    )

    if not merchant_url or current_price is None:
        return {
            "accepted": False,
            "original_price": current_price,
            "merchant_response": "Negotiation unavailable because price or merchant endpoint is missing.",
        }

    budget = shopping_goal.get("budget")

    query = f"""
NEGOTIATE PRODUCT OFFER

Product: {product_name}
Current unit price: ₹{current_price}
Quantity: {quantity}
Customer budget/target if supplied: {budget}

The customer is considering this purchase. Please provide your best
available price for this quantity, including any legitimate bulk discount.
Do not invent a discount. If no discount is available, say so clearly.
This is a price inquiry, not purchase authorization.
"""

    response = await ask_merchant(query.strip(), merchant_url)

    match = re.search(
        r"final unit price\s*:\s*[₹Rs.INR ]*([0-9]+(?:\.[0-9]+)?)",
        response,
        re.IGNORECASE,
    )
    proposed = float(match.group(1)) if match else None
    accepted = proposed is not None and 0 <= proposed < current_price
    effective_unit_price = proposed if accepted else current_price
    discount_amount = (
        round(current_price - effective_unit_price, 2) if accepted else None
    )
    discount_percent = (
        round((discount_amount / current_price) * 100, 2)
        if accepted and current_price else None
    )

    return {
        "merchant": selected_offer.get("merchant"),
        "merchant_url": merchant_url,
        "product_name": product_name,
        "original_price": current_price,
        "proposed_price": proposed,
        "effective_unit_price": effective_unit_price,
        "quantity": quantity,
        "estimated_total": effective_unit_price * quantity,
        "accepted": accepted,
        "discount_amount": discount_amount,
        "discount_percent": discount_percent,
        "merchant_response": response,
        "reasoning": (
            "Merchant supplied a lower final unit price."
            if accepted else "Merchant did not supply a lower verified final price."
        ),
    }
