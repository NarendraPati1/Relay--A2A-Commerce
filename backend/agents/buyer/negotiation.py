from agents.buyer.llm import negotiation_decision_llm
from agents.buyer.a2a_client import ask_merchant


# ============================================================
# 1. DECIDE WHETHER TO NEGOTIATE
# ============================================================

def decide_negotiation(
    user_query: str,
    shopping_goal: dict,
    selected_offer: dict,
):
    result = negotiation_decision_llm.invoke({
        "user_query": user_query,
        "shopping_goal": shopping_goal,
        "selected_offer": selected_offer,
    })

    return {
        "negotiation_requested": result.should_negotiate,
        "negotiation_reasoning": result.reasoning,
    }


# ============================================================
# 2. NEGOTIATE WITH MERCHANT
# ============================================================

async def negotiate_offer(
    selected_offer: dict,
    shopping_goal: dict,
):
    merchant_url = selected_offer["merchant_url"]
    product_name = selected_offer["product_name"]
    current_price = selected_offer["price"]

    budget = shopping_goal.get("budget")

    # If customer has a budget, use it as the
    # negotiation target.
    if budget is not None:
        target_price = budget
    else:
        # Otherwise ask merchant for its best price.
        target_price = current_price

    negotiation_query = (
        f"NEGOTIATE\n"
        f"Product: {product_name}\n"
        f"Current price: ₹{current_price}\n"
        f"Customer target price: ₹{target_price}\n"
        f"Quantity: {shopping_goal.get('quantity')}\n"
        f"Please provide your best possible price."
    )

    response = await ask_merchant(
        query=negotiation_query,
        merchant_url=merchant_url,
    )

    return {
        "merchant": selected_offer["merchant"],
        "merchant_url": merchant_url,
        "product_name": product_name,
        "original_price": current_price,
        "target_price": target_price,
        "merchant_response": response,
    }