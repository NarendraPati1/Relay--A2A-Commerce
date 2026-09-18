from copy import deepcopy
from typing import TypedDict, Any


_NEW_REQUEST_RESET = {
    "cart": {}, "cart_total": 0, "cart_complete": False,
    "selected_offer": None, "selected_offers": [], "valid_offers": [],
    "rejected_offers": [], "item_evaluations": {}, "validation_passed": False,
    "stock_valid": False, "price_valid": False, "constraints_valid": False,
    "negotiation_requested": False, "negotiation_result": None,
    "negotiation_reasoning": None, "awaiting_confirmation": False,
    "purchase_ready": False, "user_confirmation": None,
    "confirmation_type": None, "cart_order_id": None,
    "cart_payment_status": None, "cart_order_status": None,
    "razorpay_order_id": None, "razorpay_payment_id": None,
    "razorpay_signature": None, "razorpay_payment_verified": False,
    "merchant_payment_orders": [],
    "merchant_recommendations": [],
}


def reset_for_new_request() -> dict[str, Any]:
    """Return fresh state so unrelated requests cannot inherit a cart."""
    return deepcopy(_NEW_REQUEST_RESET)


class BuyerState(TypedDict, total=False):
    user_query: str
    session_id: str
    buyer_id: str
    memory_context: dict[str, Any]

    intent: str
    conversation_action: str
    quantity_planning_required: bool
    items: list[dict[str, Any]]

    product_query: str | None
    quantity: int | None
    people_count: int | None
    duration_days: int | None
    budget: float | None
    brand_preference: str | None
    pack_size: str | None
    constraints: list[str]

    shopping_goal: dict[str, Any]
    personalized_preferences: dict[str, Any]

    requirement_plan: dict[str, Any]
    product_candidates: list[dict[str, Any]]
    item_candidates: dict[str, list[dict[str, Any]]]

    relevant_product_candidates: list[dict[str, Any]]
    irrelevant_product_candidates: list[dict[str, Any]]
    item_relevance: dict[str, dict[str, Any]]

    merchants: list[dict[str, Any]]
    merchant_offers: list[dict[str, Any]]
    item_offers: dict[str, list[dict[str, Any]]]

    normalized_offers: list[dict[str, Any]]
    item_normalized_offers: dict[str, list[dict[str, Any]]]

    valid_offers: list[dict[str, Any]]
    rejected_offers: list[dict[str, Any]]
    selected_offer: dict[str, Any] | None
    selected_offers: list[dict[str, Any]]
    item_evaluations: dict[str, dict[str, Any]]
    evaluation_reasoning: str | None

    cart: dict[str, Any]
    cart_total: float
    cart_complete: bool

    negotiation_requested: bool
    negotiation_result: dict[str, Any] | None
    negotiation_reasoning: str | None

    substitution_requested: bool
    substitution_reasoning: str | None
    substitute_candidates: list[dict[str, Any]]
    selected_substitute: dict[str, Any] | None
    substitution_attempted: bool
    substitution_item: str | None
    item_substitutions: dict[str, dict[str, Any]]

    stock_valid: bool
    price_valid: bool
    constraints_valid: bool
    validation_passed: bool
    item_validations: dict[str, dict[str, Any]]

    purchase_ready: bool
    order_id: str | None
    payment_status: str | None
    order_status: str | None

    cart_order_id: str | None
    cart_payment_status: str | None
    cart_order_status: str | None

    razorpay_order_id: str | None
    razorpay_payment_id: str | None
    razorpay_signature: str | None
    razorpay_payment_verified: bool
    merchant_payment_orders: list[dict[str, Any]]
    merchant_recommendations: list[dict[str, Any]]

    awaiting_confirmation: bool
    user_confirmation: str | None
    confirmation_type: str | None

    final_response: str
