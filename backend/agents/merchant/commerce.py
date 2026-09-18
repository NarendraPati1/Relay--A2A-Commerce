from __future__ import annotations

import re
from pathlib import Path

from agents.merchant.ledger import MerchantLedger
from agents.merchant.payments import RazorpayTestGateway
from agents.merchant.recommendations import MerchantRecommendationPolicy


class MerchantCommerceService:
    def __init__(
        self,
        merchant_id: str,
        merchant_name: str,
        inventory: dict,
        discount_rules: list[tuple[int, float]] | None = None,
        ledger: MerchantLedger | None = None,
        payment_gateway: RazorpayTestGateway | None = None,
        recommendation_policy: dict | None = None,
        **_: object,
    ):
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.inventory = inventory
        self.discount_rules = sorted(discount_rules or [], key=lambda rule: rule[0])
        self.ledger = ledger or MerchantLedger(
            Path(__file__).resolve().parent.parent.parent
            / "data" / "merchant_ledgers" / f"{merchant_id}.sqlite3"
        )
        self.payment_gateway = payment_gateway or RazorpayTestGateway()
        self.recommendations = MerchantRecommendationPolicy(
            inventory, recommendation_policy,
        )

    def handle_request(self, request_text: str) -> str:
        if "CREATE MERCHANT PAYMENT ORDER" in request_text:
            return self._create_payment_order(request_text)

        if "GET MERCHANT RECOMMENDATIONS" in request_text:
            return self._recommend(request_text)

        product_name = self._find_product(request_text)

        if product_name is None:
            return f"{request_text} is not available."

        product = self.inventory[product_name]

        if product.get("stock", 0) <= 0:
            self.ledger.record_event(self.merchant_id, "offer_rejected", {
                "product_name": product_name, "reason": "out_of_stock",
            })
            return f"{product_name} is not available."

        if "NEGOTIATE PRODUCT OFFER" in request_text:
            return self._negotiate(product_name, product, request_text)

        self.ledger.record_event(self.merchant_id, "offer_quoted", {
            "product_name": product_name, "unit_price": product["price"],
        })

        return (
            f"{product_name} is available. "
            f"Price: ₹{product['price']}. "
            f"Stock: {product['stock']}."
        )

    def _negotiate(self, product_name: str, product: dict, request_text: str) -> str:
        quantity_match = re.search(r"Quantity:\s*(\d+)", request_text, re.I)
        quantity = int(quantity_match.group(1)) if quantity_match else 1
        discount = 0.0
        for minimum_quantity, percentage in self.discount_rules:
            if quantity >= minimum_quantity:
                discount = percentage

        if discount <= 0:
            self.ledger.record_event(self.merchant_id, "negotiation_declined", {
                "product_name": product_name, "quantity": quantity,
            })
            return (
                f"No bulk discount is available for {product_name} at quantity {quantity}. "
                f"Current unit price: ₹{product['price']}."
            )

        final_price = round(product["price"] * (1 - discount / 100), 2)
        self.ledger.record_event(self.merchant_id, "negotiation_accepted", {
            "product_name": product_name, "quantity": quantity,
            "original_unit_price": product["price"], "final_unit_price": final_price,
        })
        return (
            f"Negotiated offer for {product_name}. Quantity: {quantity}. "
            f"Final unit price: ₹{final_price:g}. Discount: {discount:g}%. "
            f"Stock: {product['stock']}."
        )

    def _create_payment_order(self, request_text: str) -> str:
        product_name = self._find_product(request_text)
        quantity_match = re.search(r"Quantity:\s*(\d+)", request_text, re.I)
        key_match = re.search(r"Idempotency-Key:\s*([^\s]+)", request_text, re.I)
        buyer_match = re.search(r"Buyer-Reference:\s*([^\n]+)", request_text, re.I)
        if not product_name or not quantity_match or not key_match:
            return "Payment order rejected: product, positive quantity, and idempotency key are required."

        quantity = int(quantity_match.group(1))
        product = self.inventory[product_name]
        if quantity <= 0 or product.get("stock", 0) < quantity:
            return "Payment order rejected: the requested quantity is not available."

        transaction, created = self.ledger.create_pending_transaction(
            merchant_id=self.merchant_id,
            idempotency_key=key_match.group(1),
            buyer_reference=buyer_match.group(1).strip() if buyer_match else None,
            product_name=product_name,
            quantity=quantity,
            unit_price=float(product["price"]),
        )
        if transaction.get("payment_order_id"):
            return self._payment_order_response(transaction)

        try:
            gateway_res = self.payment_gateway.create_order(
                transaction_id=transaction["transaction_id"],
                amount_inr=float(transaction["total_amount"]),
            )
            if isinstance(gateway_res, dict):
                payment_order_id = gateway_res["order_id"]
                payment_link_url = gateway_res.get("payment_link_url", f"https://rzp.io/i/{payment_order_id}")
            else:
                payment_order_id = str(gateway_res)
                payment_link_url = f"https://rzp.io/i/{payment_order_id}"
        except Exception as error:
            self.ledger.record_event(self.merchant_id, "payment_order_failed", {
                "reason": type(error).__name__,
            }, transaction["transaction_id"])
            return "Payment order could not be created. No payment has been taken."

        self.ledger.attach_payment_order(transaction["transaction_id"], payment_order_id)
        transaction["payment_order_id"] = payment_order_id
        transaction["payment_link_url"] = payment_link_url
        self.ledger.record_event(self.merchant_id, "payment_order_created", {
            "amount": transaction["total_amount"], "currency": "INR", "payment_link_url": payment_link_url,
        }, transaction["transaction_id"])
        return self._payment_order_response(transaction)

    def _recommend(self, request_text: str) -> str:
        product_name = self._find_product(request_text)
        if not product_name:
            return "No optional recommendations are available for this request."
        recommendations = self.recommendations.for_product(product_name)
        self.ledger.record_event(self.merchant_id, "recommendations_requested", {
            "product_name": product_name, "count": len(recommendations),
        })
        if not recommendations:
            return "No optional recommendations are available for this product."
        offers = "; ".join(
            f"{item['type']}: {item['product_name']} at ₹{item['unit_price']:g}"
            for item in recommendations
        )
        return f"Optional merchant recommendations for {product_name}: {offers}."

    def _payment_order_response(self, transaction: dict) -> str:
        link_str = f" Razorpay payment link: {transaction.get('payment_link_url', '')}." if transaction.get("payment_link_url") else ""
        return (
            f"Merchant payment order created. Transaction: {transaction['transaction_id']}. "
            f"Razorpay order: {transaction['payment_order_id']}.{link_str} "
            f"Amount: ₹{float(transaction['total_amount']):g}. Status: payment_pending."
        )

    def verify_payment(
        self,
        *,
        transaction_id: str,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:
        transaction = self.ledger.transaction_for_payment_order(self.merchant_id, order_id)
        if not transaction or transaction["transaction_id"] != transaction_id:
            return False
        if transaction["status"] == "paid":
            return True
        if not self.payment_gateway.verify_payment_signature(
            order_id=order_id, payment_id=payment_id, signature=signature,
        ):
            self.ledger.record_event(self.merchant_id, "payment_verification_failed", {
                "reason": "invalid_signature",
            }, transaction_id)
            return False
        self.ledger.mark_payment_verified(
            transaction_id=transaction_id,
            payment_id=payment_id,
            verification_source="checkout_signature",
        )
        return True


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
