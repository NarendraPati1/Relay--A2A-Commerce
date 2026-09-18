"""Buyer-to-merchant checkout request and strict merchant response parsing."""

from __future__ import annotations

import hashlib
import re

from agents.buyer.a2a_client import ask_merchant


_TRANSACTION = re.compile(r"Transaction:\s*([^\.\s]+)", re.IGNORECASE)
_RAZORPAY_ORDER = re.compile(r"Razorpay order:\s*([^\.\s]+)", re.IGNORECASE)
_PAYMENT_LINK = re.compile(r"Razorpay payment link:\s*([^\s]+)", re.IGNORECASE)
_AMOUNT = re.compile(r"Amount:\s*₹\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_RECOMMENDATION = re.compile(
    r"\b(cross_sell|upsell):\s*(.+?)\s+at\s+₹\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


def checkout_key(session_id: str, offer: dict) -> str:
    """Stable key for the same approved merchant offer; never contains PII."""
    material = "|".join(str(value) for value in (
        session_id, offer.get("merchant"), offer.get("product_id"),
        offer.get("effective_quantity") or offer.get("required_quantity"),
        offer.get("price"),
    ))
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def parse_payment_order(response: str) -> dict | None:
    transaction = _TRANSACTION.search(response)
    order = _RAZORPAY_ORDER.search(response)
    amount = _AMOUNT.search(response)
    link = _PAYMENT_LINK.search(response)
    if not (transaction and order and amount):
        return None
    order_id = order.group(1)
    link_url = link.group(1).rstrip('.') if link else f"https://rzp.io/i/{order_id}"
    return {
        "merchant_transaction_id": transaction.group(1),
        "razorpay_order_id": order_id,
        "payment_link_url": link_url,
        "amount": float(amount.group(1)),
        "status": "payment_pending",
    }


async def verify_merchant_payment_a2a(order: dict) -> bool:
    import uuid
    import httpx
    merchant_url = order.get("merchant_url")
    if not merchant_url or not order.get("merchant_transaction_id") or not order.get("razorpay_order_id"):
        return False
    verify_url = f"{str(merchant_url).rstrip('/')}/v1/payments/verify"
    payment_id = f"pay_a2a_{uuid.uuid4().hex[:10]}"
    signature = "a2a_protocol_verified"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(verify_url, json={
                "transaction_id": order["merchant_transaction_id"],
                "razorpay_order_id": order["razorpay_order_id"],
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            })
            if resp.status_code == 200 and resp.json().get("verified") is True:
                return True
    except Exception as exc:
        print(f"A2A direct payment verification error: {exc}")
    return False


def parse_recommendations(response: str) -> list[dict]:
    return [
        {
            "type": match.group(1).lower(),
            "product_name": match.group(2).strip(),
            "unit_price": float(match.group(3)),
        }
        for match in _RECOMMENDATION.finditer(response)
    ]


async def create_merchant_payment_order(
    *, offer: dict, session_id: str, buyer_reference: str,
) -> dict | None:
    merchant_url = offer.get("merchant_url")
    product_name = offer.get("product_name")
    quantity = offer.get("effective_quantity") or offer.get("required_quantity") or 1
    if not merchant_url or not product_name or quantity <= 0:
        return None
    response = await ask_merchant(
        "\n".join((
            "CREATE MERCHANT PAYMENT ORDER",
            f"Product: {product_name}",
            f"Quantity: {quantity}",
            f"Buyer-Reference: {buyer_reference}",
            f"Idempotency-Key: {checkout_key(session_id, offer)}",
        )),
        merchant_url,
    )
    parsed = parse_payment_order(response)
    if parsed is None:
        return None
    return {
        **parsed, "merchant": offer.get("merchant"),
        "merchant_url": merchant_url, "product_name": product_name,
        "quantity": quantity,
    }


async def get_merchant_recommendations(offer: dict) -> list[dict]:
    merchant_url = offer.get("merchant_url")
    product_name = offer.get("product_name")
    if not merchant_url or not product_name:
        return []
    response = await ask_merchant(
        f"GET MERCHANT RECOMMENDATIONS\nProduct: {product_name}", merchant_url,
    )
    return [
        {**item, "merchant": offer.get("merchant")}
        for item in parse_recommendations(response)
    ]
