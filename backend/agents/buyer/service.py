"""Application boundary for the buyer agent.

The graph owns shopping decisions; this module owns request validation,
conversation isolation, and the deliberately small response returned to a
client.  The in-memory store is suitable for local development only.  A
production deployment can implement ``BuyerSessionRepository`` with Redis or
a database without changing the HTTP contract.
"""

from __future__ import annotations

import asyncio
import copy
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any, Protocol

from agents.buyer.memory import BuyerMemory
from agents.buyer.security import SAFE_REFUSAL, assess_customer_message


_RATE_LIMIT_WAIT = re.compile(
    r"try again in\s*(?:(\d+)m)?\s*(\d+(?:\.\d+)?)s",
    re.IGNORECASE,
)


def _rate_limit_delay_seconds(error: Exception) -> float | None:
    if getattr(error, "status_code", None) != 429 and "ratelimit" not in type(error).__name__.lower():
        return None
    match = _RATE_LIMIT_WAIT.search(str(error))
    if match:
        return int(match.group(1) or 0) * 60 + float(match.group(2))
    return 60.0


def _rate_limit_response(session_id: str, seconds: float) -> dict[str, Any]:
    minutes = max(1, round(seconds / 60))
    return {
        "session_id": session_id,
        "reply": (
            "The language-model provider is temporarily rate limited; your "
            "cart has not changed. Please try again in about "
            f"{minutes} minute{'s' if minutes != 1 else ''}."
        ),
        "cart": None,
        "checkout": {
            "awaiting_confirmation": False,
            "payment_status": None,
            "order_status": None,
            "order_id": None,
        },
    }


class BuyerGraph(Protocol):
    async def ainvoke(self, state: dict[str, Any]) -> Mapping[str, Any]: ...


class BuyerSessionRepository(Protocol):
    async def get(self, session_id: str) -> dict[str, Any] | None: ...

    async def put(self, session_id: str, state: dict[str, Any]) -> None: ...


class InMemoryBuyerSessionRepository:
    """Local-development repository with defensive copies between requests."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            state = self._sessions.get(session_id)
            return copy.deepcopy(state) if state is not None else None

    async def put(self, session_id: str, state: dict[str, Any]) -> None:
        async with self._lock:
            self._sessions[session_id] = copy.deepcopy(state)


class BuyerService:
    """Runs one buyer turn while keeping each customer session isolated."""

    def __init__(
        self,
        graph: BuyerGraph,
        sessions: BuyerSessionRepository | None = None,
        memories: BuyerMemory | None = None,
    ) -> None:
        self._graph = graph
        self._sessions = sessions or InMemoryBuyerSessionRepository()
        self._memories = memories or BuyerMemory()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._rate_limit_until = 0.0

    async def send_message(
        self,
        message: str,
        session_id: str | None = None,
        buyer_id: str | None = None,
    ) -> dict[str, Any]:
        message = message.strip()
        if not message:
            raise ValueError("message must not be empty")
        if len(message) > 4_000:
            raise ValueError("message must be at most 4000 characters")

        session_id = session_id or str(uuid.uuid4())
        buyer_id = buyer_id or f"session:{session_id}"
        if len(buyer_id) > 128:
            raise ValueError("buyer_id must be at most 128 characters")

        safety = assess_customer_message(message)
        if safety.blocked:
            await asyncio.to_thread(
                self._memories.record_safety_event,
                buyer_id,
                session_id,
                safety.category or "unknown",
            )
            return {
                "session_id": session_id,
                "reply": SAFE_REFUSAL,
                "cart": None,
                "checkout": {
                    "awaiting_confirmation": False,
                    "payment_status": None,
                    "order_status": None,
                    "order_id": None,
                },
            }

        remaining = self._rate_limit_until - time.monotonic()
        if remaining > 0:
            return _rate_limit_response(session_id, remaining)
        lock = await self._lock_for(session_id)

        # Serializing a session prevents simultaneous requests from producing
        # two conflicting carts or purchase-confirmation states.
        async with lock:
            previous_state = await self._sessions.get(session_id)
            if previous_state is None:
                previous_state = await asyncio.to_thread(
                    self._memories.get_workflow, session_id, buyer_id,
                )
            memory_context = await asyncio.to_thread(
                self._memories.get_context, buyer_id, session_id,
            )
            try:
                result = await self._graph.ainvoke({
                    **(previous_state or {}),
                    "session_id": session_id,
                    "buyer_id": buyer_id,
                    "user_query": message,
                    "memory_context": memory_context,
                    "personalized_preferences": memory_context["buyer_preferences"],
                })
            except Exception as error:
                delay = _rate_limit_delay_seconds(error)
                if delay is None:
                    raise
                self._rate_limit_until = time.monotonic() + delay
                return _rate_limit_response(session_id, delay)
            next_state = dict(result)
            await self._sessions.put(session_id, next_state)
            await asyncio.to_thread(
                self._memories.record_turn, buyer_id, session_id, next_state,
            )

        return project_response(session_id, next_state)

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            return lock


def project_response(session_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    """Return client-safe data, never the graph's private reasoning/state."""
    cart = state.get("cart") or {}
    items = [
        {
            "product_name": item.get("product_name"),
            "merchant": item.get("merchant"),
            "quantity": item.get("quantity"),
            "quantity_is_estimated": bool(item.get("quantity_is_estimated")),
            "unit_price": item.get("unit_price"),
            "total_price": item.get("total_price"),
            "currency": "INR",
            "negotiated": bool(item.get("negotiated")),
        }
        for item in cart.get("items", [])
    ]

    audit_log = [{
        "source": "buyer",
        "event": "request_processed",
        "detail": "Requirement and safety checks completed.",
    }]
    selected_offers = state.get("selected_offers", [])
    if selected_offers:
        audit_log.append({
            "source": "buyer",
            "event": "verified_offer_selected",
            "detail": "A verified merchant offer was selected for the cart.",
        })
    if any(bool(offer.get("negotiated")) for offer in selected_offers):
        audit_log.append({
            "source": "merchant",
            "event": "negotiated_price_verified",
            "detail": "A merchant returned an explicitly lower final price.",
        })
    if state.get("awaiting_confirmation"):
        audit_log.append({
            "source": "buyer",
            "event": "approval_required",
            "detail": "No payment order can be created until the buyer confirms.",
        })
    for order in state.get("merchant_payment_orders", []):
        audit_log.append({
            "source": "merchant",
            "event": "payment_order_created",
            "detail": f"{order.get('merchant')} created a pending payment order.",
        })

    return {
        "session_id": session_id,
        "reply": state.get("final_response")
        or "I could not generate a response. Please try again.",
        "cart": {
            "items": items,
            "total": cart.get("total", 0),
            "currency": "INR",
            "complete": bool(cart.get("complete")),
        } if items else None,
        "checkout": {
            "awaiting_confirmation": bool(state.get("awaiting_confirmation")),
            "payment_status": state.get("cart_payment_status"),
            "order_status": state.get("cart_order_status"),
            # This is an opaque payment-provider order reference, not a
            # payment success signal.
            "order_id": state.get("cart_order_id"),
            "merchant_orders": [
                {
                    "merchant": order.get("merchant"),
                    "order_id": order.get("razorpay_order_id"),
                    "transaction_id": order.get("merchant_transaction_id"),
                    "amount": order.get("amount"),
                    "status": order.get("status"),
                    "payment_link_url": order.get("payment_link_url"),
                    "paid_by_agent": order.get("paid_by_agent", False),
                    # A merchant owns verification.  This URL contains no
                    # credential and only accepts a signature bound to its
                    # own transaction/order pair.
                    "verification_url": (
                        f"{str(order.get('merchant_url')).rstrip('/')}/v1/payments/verify"
                        if order.get("merchant_url") else None
                    ),
                }
                for order in state.get("merchant_payment_orders", [])
            ],
        },
        "recommendations": [
            {
                "merchant": recommendation.get("merchant"),
                "type": recommendation.get("type"),
                "product_name": recommendation.get("product_name"),
                "unit_price": recommendation.get("unit_price"),
                "currency": "INR",
            }
            for recommendation in state.get("merchant_recommendations", [])
        ],
        "audit_log": audit_log,
    }
