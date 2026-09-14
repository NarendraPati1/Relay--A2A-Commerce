import uuid


def purchase_offer(
    selected_offer: dict,
    shopping_goal: dict,
):

    quantity = shopping_goal.get(
        "quantity"
    ) or 1

    price = selected_offer["price"]

    total_price = price * quantity

    order_id = (
        "ORD-"
        + uuid.uuid4().hex[:8].upper()
    )

    return {
        "order_id": order_id,
        "merchant": selected_offer["merchant"],
        "merchant_url": selected_offer["merchant_url"],
        "product_name": selected_offer["product_name"],
        "quantity": quantity,
        "unit_price": price,
        "total_price": total_price,
        "payment_status": "pending",
        "order_status": "created",
    }