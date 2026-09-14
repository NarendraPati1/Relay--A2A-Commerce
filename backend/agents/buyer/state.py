from typing import TypedDict, Any


class BuyerState(TypedDict, total=False):

    # ============================================================
    # REQUEST
    # ============================================================

    user_query: str
    session_id: str

    # ============================================================
    # UNDERSTANDING
    # ============================================================

    intent: str

    # ------------------------------------------------------------
    # MULTI-ITEM SUPPORT
    # ------------------------------------------------------------

    items: list[dict[str, Any]]

    # ============================================================
    # LEGACY / SINGLE-ITEM FIELDS
    #
    # Kept temporarily for compatibility with existing modules.
    # ============================================================

    product_query: str | None
    quantity: int | None
    budget: float | None
    brand_preference: str | None
    pack_size: str | None
    constraints: list[str]

    # ============================================================
    # SHOPPING GOAL
    # ============================================================

    shopping_goal: dict[str, Any]

    personalized_preferences: dict[str, Any]

    # ============================================================
    # PRODUCT DISCOVERY
    # ============================================================

    product_candidates: list[dict[str, Any]]

    item_candidates: dict[str, list[dict[str, Any]]]

    # ============================================================
    # RELEVANCE
    # ============================================================

    relevant_product_candidates: list[dict[str, Any]]

    irrelevant_product_candidates: list[dict[str, Any]]

    item_relevance: dict[
        str,
        dict[str, list[dict[str, Any]]]
    ]

    # ============================================================
    # MERCHANT DISCOVERY
    # ============================================================

    merchants: list[dict[str, Any]]

    # ============================================================
    # MERCHANT OFFERS
    # ============================================================

    merchant_offers: list[dict[str, Any]]

    item_offers: dict[str, list[dict[str, Any]]]

    # ============================================================
    # NORMALIZED OFFERS
    # ============================================================

    normalized_offers: list[dict[str, Any]]

    item_normalized_offers: dict[
        str,
        list[dict[str, Any]]
    ]

    # ============================================================
    # EVALUATION
    # ============================================================

    valid_offers: list[dict[str, Any]]

    rejected_offers: list[dict[str, Any]]

    selected_offer: dict[str, Any] | None

    evaluation_reasoning: str | None

    # ------------------------------------------------------------
    # MULTI-ITEM RESULTS
    # ------------------------------------------------------------

    item_evaluations: dict[
        str,
        dict[str, Any]
    ]

    selected_offers: list[dict[str, Any]]

    # ============================================================
    # CART
    # ============================================================

    cart: dict[str, Any]

    cart_total: float

    cart_complete: bool

    # ============================================================
    # NEGOTIATION
    # ============================================================

    negotiation_requested: bool

    negotiation_result: dict[str, Any] | None

    # ============================================================
    # SUBSTITUTION
    # ============================================================

    substitution_requested: bool

    substitution_reasoning: str | None

    substitute_candidates: list[dict[str, Any]]

    selected_substitute: dict[str, Any] | None

    substitution_attempted: bool

    substitution_item: str | None

    # ------------------------------------------------------------
    # PER-ITEM SUBSTITUTION
    # ------------------------------------------------------------

    item_substitutions: dict[
        str,
        dict[str, Any]
    ]

    # ============================================================
    # VALIDATION
    # ============================================================

    stock_valid: bool

    price_valid: bool

    constraints_valid: bool

    validation_passed: bool

    # ------------------------------------------------------------
    # PER-ITEM VALIDATION
    # ------------------------------------------------------------

    item_validations: dict[
        str,
        dict[str, Any]
    ]

    # ============================================================
    # PURCHASE
    # ============================================================

    purchase_ready: bool

    order_id: str | None

    payment_status: str | None

    order_status: str | None

    # ============================================================
    # CART PURCHASE
    # ============================================================

    cart_order_id: str | None

    cart_payment_status: str | None

    cart_order_status: str | None

    # ------------------------------------------------------------
    # RAZORPAY
    # ------------------------------------------------------------

    razorpay_order_id: str | None

    razorpay_payment_id: str | None

    razorpay_signature: str | None

    razorpay_payment_verified: bool

    # ============================================================
    # HUMAN-IN-THE-LOOP
    #
    # Reserved for later.
    # No HITL logic is implemented yet.
    # ============================================================

    awaiting_confirmation: bool

    user_confirmation: str | None

    confirmation_type: str | None

    # ============================================================
    # RESPONSE
    # ============================================================

    final_response: str