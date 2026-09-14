from langgraph.graph import StateGraph, START, END

from agents.buyer.state import BuyerState

from agents.buyer.llm import (
    buyer_intent_llm,
    shopping_goal_llm,
)

from agents.buyer.evaluation import evaluate_options
from agents.buyer.normalization import normalize_offers

from agents.buyer.substitution import (
    decide_substitution,
    select_substitute,
)

from agents.buyer.relevance import check_relevance

from retrieval.hybrid import search_products
from core.registry import MERCHANT_REGISTRY
from agents.buyer.a2a_client import ask_merchant


# ============================================================
# 1. UNDERSTAND
# ============================================================

def understand(state: BuyerState):

    print("→ Understanding")

    result = buyer_intent_llm.invoke({
        "user_query": state["user_query"]
    })

    items = [
        item.model_dump()
        for item in result.items
    ]

    return {
        "intent": result.intent,
        "items": items,

        # Legacy compatibility
        "product_query": (
            items[0]["product_query"]
            if items else None
        ),
        "quantity": (
            items[0]["quantity"]
            if items else None
        ),
        "budget": (
            items[0]["budget"]
            if items else None
        ),
        "brand_preference": (
            items[0]["brand_preference"]
            if items else None
        ),
        "pack_size": (
            items[0]["pack_size"]
            if items else None
        ),
        "constraints": (
            items[0]["constraints"]
            if items else []
        ),
    }


# ============================================================
# 2. BUILD SHOPPING GOAL
# ============================================================


def build_shopping_goal(state: BuyerState):

    print("→ Building Shopping Goal")

    buyer_intent = {
        "intent": state.get("intent"),
        "items": state.get("items", []),
    }

    result = shopping_goal_llm.invoke({
        "user_query": state["user_query"],
        "buyer_intent": buyer_intent,
        "personalized_preferences": state.get(
            "personalized_preferences",
            {},
        ),
    })

    return {
        "shopping_goal": result.model_dump()
    }


# ============================================================
# 3. PRODUCT DISCOVERY
# ============================================================

def retrieve_product(state: BuyerState):

    print("→ Product Discovery")

    items = state.get(
        "items",
        [],
    )

    item_candidates = {}
    all_candidates = []

    for item in items:

        product_query = item.get(
            "product_query"
        )

        if not product_query:
            continue

        print(
            f"   Searching: {product_query}"
        )

        result = search_products(
            query=product_query,
            top_k=5,
        )

        candidates = []

        for result_item in result["candidates"]:

            product = result_item["product"]

            candidate = {
                "id": product["id"],
                "name": product["name"],
                "description": product["description"],
                "category": product["category"],
                "brand": product["brand"],
                "pack_size": product["pack_size"],
                "exact_score": result_item[
                    "exact_score"
                ],
                "vector_score": result_item[
                    "vector_score"
                ],
                "rrf_score": result_item[
                    "rrf_score"
                ],
            }

            candidates.append(candidate)
            all_candidates.append(candidate)

        item_candidates[
            product_query
        ] = candidates

    print(
        f"→ Items discovered: "
        f"{len(item_candidates)}"
    )

    return {
        "item_candidates": item_candidates,
        "product_candidates": all_candidates,
    }


# ============================================================
# 4. RELEVANCE GATE
# ============================================================

def relevance_gate(state: BuyerState):

    print("→ Relevance Gate")

    items = state.get(
        "items",
        [],
    )

    item_candidates = state.get(
        "item_candidates",
        {},
    )

    item_relevance = {}

    all_relevant = []
    all_rejected = []

    for item in items:

        product_query = item.get(
            "product_query"
        )

        candidates = item_candidates.get(
            product_query,
            [],
        )

        item_goal = {
            "product": product_query,
            "quantity": item.get("quantity"),
            "budget": item.get("budget"),
            "preferred_brand": item.get(
                "brand_preference"
            ),
            "preferred_pack_size": item.get(
                "pack_size"
            ),
            "constraints": item.get(
                "constraints",
                [],
            ),
        }

        relevant, rejected = check_relevance(
            user_query=product_query,
            shopping_goal=item_goal,
            product_candidates=candidates,
        )

        item_relevance[
            product_query
        ] = {
            "relevant": relevant,
            "rejected": rejected,
        }

        all_relevant.extend(relevant)
        all_rejected.extend(rejected)

        print(
            f"   {product_query}: "
            f"{len(relevant)} relevant, "
            f"{len(rejected)} rejected"
        )

    return {
        "item_relevance": item_relevance,
        "relevant_product_candidates": all_relevant,
        "irrelevant_product_candidates": all_rejected,
    }


# ============================================================
# 5. RELEVANCE ROUTER
# ============================================================

def route_after_relevance(state: BuyerState):

    items = state.get(
        "items",
        [],
    )

    item_relevance = state.get(
        "item_relevance",
        {},
    )

    for item in items:

        product_query = item.get(
            "product_query"
        )

        result = item_relevance.get(
            product_query,
            {},
        )

        if result.get("relevant"):

            return "discover"

    return "decide_substitution"


# ============================================================
# 6. MERCHANT DISCOVERY
# ============================================================

def discover(state: BuyerState):

    print("→ Merchant Discovery")

    return {
        "merchants": MERCHANT_REGISTRY
    }


# ============================================================
# 7. QUERY MERCHANTS
#
# Every requested item is handled independently.
#
# If a substitute exists for a particular item,
# only that item's product query is replaced.
# ============================================================

async def query_merchants(state: BuyerState):

    print("→ Query Merchants")

    items = state.get(
        "items",
        [],
    )

    item_relevance = state.get(
        "item_relevance",
        {},
    )

    item_substitutions = state.get(
        "item_substitutions",
        {},
    )

    merchants = state.get(
        "merchants",
        [],
    )

    item_offers = {}
    all_offers = []

    for item in items:

        item_query = item.get(
            "product_query"
        )

        if not item_query:
            continue

        # ----------------------------------------------------
        # Normally use relevant exact candidates.
        # ----------------------------------------------------

        relevance = item_relevance.get(
            item_query,
            {},
        )

        product_candidates = relevance.get(
            "relevant",
            [],
        )

        # ----------------------------------------------------
        # If this specific item has a substitute,
        # query merchants for the substitute instead.
        # ----------------------------------------------------

        substitution_history = (
            item_substitutions.get(
                item_query,
                {}
            )
        )

        selected_substitute = (
            substitution_history.get(
                "selected_substitute"
            )
        )

        if selected_substitute:

            product_candidates = [
                selected_substitute
            ]

            print(
                f"   {item_query}: "
                f"using substitute "
                f"{selected_substitute.get('name') or selected_substitute.get('product_name')}"
            )

        item_offers[
            item_query
        ] = []

        # ----------------------------------------------------
        # Merchant × product
        # ----------------------------------------------------

        for merchant in merchants:

            for product in product_candidates:
                response = await ask_merchant(
                    query=product["name"],
                    merchant_url=merchant[
                        "agent_url"
                    ],
                )

                offer = {
                    "item_query": item_query,

                    "merchant": merchant[
                        "name"
                    ],

                    "merchant_url": merchant[
                        "agent_url"
                    ],

                    "product": product,

                    "response": response,
                }

                item_offers[
                    item_query
                ].append(offer)

                all_offers.append(offer)

    print(
        f"→ Merchant Offers Received: "
        f"{len(all_offers)}"
    )

    return {
        "item_offers": item_offers,

        "merchant_offers": all_offers,

        # Reset current evaluation cycle.
        "normalized_offers": [],
        "valid_offers": [],
        "rejected_offers": [],
        "selected_offer": None,
        "selected_offers": [],
        "item_evaluations": {},
    }


# ============================================================
# 8. NORMALIZE OFFERS
# ============================================================

def normalize_offers_node(state: BuyerState):

    print("→ Normalize Offers")

    merchant_offers = state.get(
        "merchant_offers",
        [],
    )

    item_normalized = {}
    all_normalized = []

    normalized = normalize_offers(
        merchant_offers
    )

    for original_offer, normalized_offer in zip(
        merchant_offers,
        normalized,
    ):

        item_query = original_offer.get(
            "item_query"
        )

        normalized_offer = {
            **normalized_offer,
            "item_query": item_query,
            "merchant_url": original_offer.get(
                "merchant_url"
            ),
            "product": original_offer.get(
                "product"
            ),
        }

        item_normalized.setdefault(
            item_query,
            [],
        ).append(
            normalized_offer
        )

        all_normalized.append(
            normalized_offer
        )

    return {
        "item_normalized_offers": item_normalized,
        "normalized_offers": all_normalized,
    }


# ============================================================
# 9. EVALUATE OPTIONS
# ============================================================

def evaluate_options_node(state: BuyerState):

    print("→ Evaluate Options")

    items = state.get(
        "items",
        [],
    )

    item_normalized_offers = state.get(
        "item_normalized_offers",
        {},
    )

    item_evaluations = {}

    selected_offers = []

    all_valid = []
    all_rejected = []

    for item in items:

        product_query = item.get(
            "product_query"
        )

        normalized_offers = (
            item_normalized_offers.get(
                product_query,
                [],
            )
        )

        item_goal = {
            "product": product_query,
            "quantity": item.get(
                "quantity"
            ),
            "budget": item.get(
                "budget"
            ),
            "preferred_brand": item.get(
                "brand_preference"
            ),
            "preferred_pack_size": item.get(
                "pack_size"
            ),
            "constraints": item.get(
                "constraints",
                [],
            ),
        }

        result = evaluate_options(
            user_query=product_query,
            shopping_goal=item_goal,
            personalized_preferences=state.get(
                "personalized_preferences",
                {},
            ),
            normalized_offers=normalized_offers,
        )

        item_evaluations[
            product_query
        ] = result

        all_valid.extend(
            result.get(
                "valid_offers",
                [],
            )
        )

        all_rejected.extend(
            result.get(
                "rejected_offers",
                [],
            )
        )

        selected_offer = result.get(
            "selected_offer"
        )

        if selected_offer:

            selected_offer = {
                **selected_offer,
                "item_query": product_query,
                "quantity": (
                    item.get("quantity")
                    or 1
                ),
            }

            selected_offers.append(
                selected_offer
            )

        print(
            f"   {product_query}: "
            f"{'selected' if selected_offer else 'no offer'}"
        )

    cart_complete = (
        len(selected_offers)
        == len(items)
        and len(items) > 0
    )

    cart_total = sum(
        offer.get("price", 0)
        * offer.get("quantity", 1)
        for offer in selected_offers
    )

    return {
        "item_evaluations": item_evaluations,

        "selected_offers": selected_offers,

        "valid_offers": all_valid,

        "rejected_offers": all_rejected,

        "selected_offer": (
            selected_offers[0]
            if len(selected_offers) == 1
            else None
        ),

        "cart_total": cart_total,

        "cart_complete": cart_complete,

        "evaluation_reasoning": (
            "All requested items have suitable offers."
            if cart_complete
            else
            "One or more requested items "
            "do not have a suitable offer."
        ),
    }


# ============================================================
# 10. EVALUATION ROUTER
# ============================================================

def route_after_evaluation(state: BuyerState):

    selected_offers = state.get(
        "selected_offers",
        [],
    )

    items = state.get(
        "items",
        [],
    )

    if (
        len(selected_offers)
        == len(items)
    ):
        return "cart_complete"

    return "cart_incomplete"


# ============================================================
# 11. DECIDE SUBSTITUTION
# ============================================================

def decide_substitution_node(state: BuyerState):

    print("→ Decide Substitution")

    items = state.get(
        "items",
        [],
    )

    item_evaluations = state.get(
        "item_evaluations",
        {},
    )

    item_substitutions = state.get(
        "item_substitutions",
        {},
    )

    for item in items:

        item_query = item.get(
            "product_query"
        )

        if not item_query:
            continue

        evaluation = item_evaluations.get(
            item_query,
            {},
        )

        # ----------------------------------------------------
        # This item already has a valid offer.
        # ----------------------------------------------------

        if evaluation.get(
            "selected_offer"
        ):
            continue

        # ----------------------------------------------------
        # Build item-specific shopping goal.
        # ----------------------------------------------------

        shopping_item = None

        for goal_item in state.get(
            "shopping_goal",
            {},
        ).get(
            "items",
            [],
        ):

            if (
                goal_item.get(
                    "product",
                    ""
                ).lower()
                == item_query.lower()
            ):

                shopping_item = goal_item
                break

        if shopping_item is None:

            shopping_item = {
                "product": item_query,
                "quantity": item.get(
                    "quantity"
                ),
                "budget": item.get(
                    "budget"
                ),
                "preferred_brand": item.get(
                    "brand_preference"
                ),
                "preferred_pack_size": item.get(
                    "pack_size"
                ),
                "constraints": item.get(
                    "constraints",
                    [],
                ),
            }

        # ----------------------------------------------------
        # Track previous substitution attempts.
        # ----------------------------------------------------

        history = (
            item_substitutions.get(
                item_query,
                {}
            )
        )

        attempted_product_ids = set(
            history.get(
                "attempted_product_ids",
                [],
            )
        )

        current_substitute = (
            history.get(
                "selected_substitute"
            )
        )

        if current_substitute:

            current_id = current_substitute.get(
                "id"
            )

            if current_id:

                attempted_product_ids.add(
                    current_id
                )

        candidates = state.get(
            "item_candidates",
            {},
        ).get(
            item_query,
            [],
        )

        rejected_offers = evaluation.get(
            "rejected_offers",
            [],
        )

        print(
            f"   Checking substitution for: "
            f"{item_query}"
        )

        result = decide_substitution(
            user_query=state["user_query"],

            original_product=item_query,

            shopping_goal=shopping_item,

            personalized_preferences=state.get(
                "personalized_preferences",
                {},
            ),

            product_candidates=candidates,

            rejected_offers=rejected_offers,

            attempted_product_ids=(
                list(attempted_product_ids)
            ),
        )

        return {
            "substitution_requested": (
                result[
                    "substitution_requested"
                ]
            ),

            "substitution_reasoning": (
                result.get(
                    "substitution_reasoning",
                    result.get("reasoning", ""),
                )
            ),

            "substitution_item": item_query,
        }

    return {
        "substitution_requested": False,

        "substitution_reasoning": (
            "No item requires substitution."
        ),

        "substitution_item": None,
    }


# ============================================================
# 12. SUBSTITUTION DECISION ROUTER
# ============================================================

def route_after_substitution_decision(
    state: BuyerState
):

    if state.get(
        "substitution_requested"
    ):
        return "select_substitute"

    return "respond"


# ============================================================
# 13. SELECT SUBSTITUTE
# ============================================================

def select_substitute_node(state: BuyerState):

    print("→ Select Substitute")

    item_query = state.get(
        "substitution_item"
    )

    if not item_query:

        return {
            "selected_substitute": None,
        }

    # --------------------------------------------------------
    # Find item shopping goal.
    # --------------------------------------------------------

    shopping_item = None

    for goal_item in state.get(
        "shopping_goal",
        {},
    ).get(
        "items",
        [],
    ):

        if (
            goal_item.get(
                "product",
                ""
            ).lower()
            == item_query.lower()
        ):

            shopping_item = goal_item
            break

    if shopping_item is None:

        return {
            "selected_substitute": None,

            "substitution_reasoning": (
                "Shopping goal for the item "
                "could not be found."
            ),
        }

    # --------------------------------------------------------
    # Previous substitution history.
    # --------------------------------------------------------

    item_substitutions = dict(
        state.get(
            "item_substitutions",
            {},
        )
    )

    history = dict(
        item_substitutions.get(
            item_query,
            {},
        )
    )

    attempted_product_ids = set(
        history.get(
            "attempted_product_ids",
            [],
        )
    )

    current_substitute = history.get(
        "selected_substitute"
    )

    if current_substitute:

        current_id = current_substitute.get(
            "id"
        )

        if current_id:

            attempted_product_ids.add(
                current_id
            )

    candidates = state.get(
        "item_candidates",
        {},
    ).get(
        item_query,
        [],
    )

    rejected_offers = state.get(
        "item_evaluations",
        {},
    ).get(
        item_query,
        {},
    ).get(
        "rejected_offers",
        [],
    )

    result = select_substitute(
        user_query=state["user_query"],

        original_product=item_query,

        shopping_goal=shopping_item,

        personalized_preferences=state.get(
            "personalized_preferences",
            {},
        ),

        product_candidates=candidates,

        rejected_offers=rejected_offers,

        attempted_product_ids=(
            list(attempted_product_ids)
        ),
    )

    selected_substitute = result.get(
        "selected_substitute"
    )

    # --------------------------------------------------------
    # Update substitution history.
    # --------------------------------------------------------

    attempted_ids = list(
        attempted_product_ids
    )

    if selected_substitute:

        selected_id = selected_substitute.get(
            "id"
        )

        if (
            selected_id
            and selected_id not in attempted_ids
        ):

            attempted_ids.append(
                selected_id
            )

    history.update({
        "requested": True,

        "selected_substitute": (
            selected_substitute
        ),

        "reasoning": result.get(
            "substitution_reasoning"
        ),

        "attempted_product_ids": (
            attempted_ids
        ),

        "attempt_count": len(
            attempted_ids
        ),
    })

    item_substitutions[
        item_query
    ] = history

    return {
        "selected_substitute": (
            selected_substitute
        ),

        "substitution_reasoning": (
            result.get(
                "substitution_reasoning",
                result.get("reasoning", ""),
            )
        ),

        "item_substitutions": (
            item_substitutions
        ),
    }


# ============================================================
# 14. SUBSTITUTE ROUTER
# ============================================================

def route_after_substitute_selection(
    state: BuyerState
):

    if state.get(
        "selected_substitute"
    ):

        return "query_merchants"

    return "respond"


# ============================================================
# 15. BUILD CART
# ============================================================

def build_cart_node(state: BuyerState):

    print("→ Build Cart")

    selected_offers = state.get(
        "selected_offers",
        [],
    )

    cart_items = []

    for offer in selected_offers:

        quantity = (
            offer.get("quantity")
            or 1
        )

        unit_price = (
            offer.get("price")
            or 0
        )

        cart_items.append({
            "item_query": offer.get(
                "item_query"
            ),

            "product_name": offer.get(
                "product_name"
            ),

            "merchant": offer.get(
                "merchant"
            ),

            "merchant_url": offer.get(
                "merchant_url"
            ),

            "quantity": quantity,

            "unit_price": unit_price,

            "total_price": (
                unit_price * quantity
            ),

            "product": offer.get(
                "product"
            ),
        })

    cart_total = sum(
        item["total_price"]
        for item in cart_items
    )

    return {
        "cart": {
            "items": cart_items,

            "total": cart_total,

            "item_count": len(
                cart_items
            ),

            "complete": state.get(
                "cart_complete",
                False,
            ),
        },

        "cart_total": cart_total,
    }


# ============================================================
# 16. VALIDATION
# ============================================================

def validate_node(state: BuyerState):

    print("→ Validation")

    selected_offers = state.get(
        "selected_offers",
        [],
    )

    items = state.get(
        "items",
        [],
    )

    item_validations = {}

    for offer in selected_offers:

        item_query = offer.get(
            "item_query"
        )

        quantity = (
            offer.get("quantity")
            or 1
        )

        stock = offer.get(
            "stock"
        )

        price = offer.get(
            "price"
        )

        # ----------------------------------------------------
        # Stock
        # ----------------------------------------------------

        stock_valid = (
            stock is not None
            and stock >= quantity
        )

        # ----------------------------------------------------
        # Price
        # ----------------------------------------------------

        item = next(
            (
                item
                for item in items
                if item.get(
                    "product_query"
                ) == item_query
            ),
            {},
        )

        budget = item.get(
            "budget"
        )

        price_valid = (
            price is not None
            and (
                budget is None
                or price <= budget
            )
        )

        # ----------------------------------------------------
        # Constraints
        # ----------------------------------------------------

        constraints_valid = True

        constraints = item.get(
            "constraints",
            []
        )

        product_name = offer.get(
            "product_name",
            ""
        ).lower()

        merchant = offer.get(
            "merchant",
            ""
        ).lower()

        for constraint in constraints:

            constraint_lower = (
                constraint.lower()
            )

            if (
                "not" in constraint_lower
                or "exclude" in constraint_lower
                or "avoid" in constraint_lower
            ):

                words = (
                    constraint_lower
                    .replace("not", "")
                    .replace("exclude", "")
                    .replace("avoid", "")
                    .strip()
                )

                if words and (
                    words in product_name
                    or words in merchant
                ):

                    constraints_valid = False
                    break

        validation_passed = (
            stock_valid
            and price_valid
            and constraints_valid
        )

        item_validations[
            item_query
        ] = {
            "stock_valid": stock_valid,
            "price_valid": price_valid,
            "constraints_valid": (
                constraints_valid
            ),
            "validation_passed": (
                validation_passed
            ),
        }

        print(
            f"   {item_query}: "
            f"stock={stock_valid}, "
            f"price={price_valid}, "
            f"constraints={constraints_valid}"
        )

    validation_passed = (
        len(items) > 0
        and len(item_validations)
        == len(items)
        and all(
            result["validation_passed"]
            for result
            in item_validations.values()
        )
    )

    stock_valid = (
        len(item_validations)
        == len(items)
        and all(
            result["stock_valid"]
            for result
            in item_validations.values()
        )
    )

    price_valid = (
        len(item_validations)
        == len(items)
        and all(
            result["price_valid"]
            for result
            in item_validations.values()
        )
    )

    constraints_valid = (
        len(item_validations)
        == len(items)
        and all(
            result["constraints_valid"]
            for result
            in item_validations.values()
        )
    )

    return {
        "item_validations": item_validations,

        "stock_valid": stock_valid,

        "price_valid": price_valid,

        "constraints_valid": constraints_valid,

        "validation_passed": (
            validation_passed
        ),

        "purchase_ready": (
            validation_passed
        ),
    }


# ============================================================
# 17. VALIDATION ROUTER
# ============================================================

def route_after_validation(
    state: BuyerState
):

    if state.get(
        "validation_passed"
    ):

        return "purchase"

    return "respond"


# ============================================================
# 18. PURCHASE
#
# Razorpay TEST MODE order creation.
#
# Checkout/HITL will be added later.
# ============================================================

def purchase_node(state: BuyerState):

    print("→ Purchase")

    if not state.get(
        "validation_passed"
    ):

        return {
            "purchase_ready": False,

            "cart_payment_status": (
                "not_started"
            ),

            "cart_order_status": (
                "not_created"
            ),
        }

    import os
    import uuid
    import razorpay

    key_id = os.getenv(
        "RAZORPAY_KEY_ID"
    )

    key_secret = os.getenv(
        "RAZORPAY_KEY_SECRET"
    )

    if not key_id or not key_secret:

        raise RuntimeError(
            "RAZORPAY_KEY_ID and "
            "RAZORPAY_KEY_SECRET "
            "must be set in the environment."
        )

    cart_total = state.get(
        "cart_total",
        0,
    )

    amount_paise = int(
        round(
            cart_total * 100
        )
    )

    receipt = (
        "cart_"
        + uuid.uuid4().hex[:12]
    )

    client = razorpay.Client(
        auth=(
            key_id,
            key_secret,
        )
    )

    razorpay_order = client.order.create({
        "amount": amount_paise,

        "currency": "INR",

        "receipt": receipt,

        "notes": {
            "source": "buyer_agent",

            "item_count": str(
                len(
                    state.get(
                        "selected_offers",
                        [],
                    )
                )
            ),
        },
    })

    razorpay_order_id = (
        razorpay_order["id"]
    )

    print(
        f"   Razorpay Order: "
        f"{razorpay_order_id}"
    )

    return {
        "purchase_ready": True,

        "cart_order_id": (
            razorpay_order_id
        ),

        "razorpay_order_id": (
            razorpay_order_id
        ),

        "cart_payment_status": (
            "pending"
        ),

        "cart_order_status": (
            "created"
        ),
    }


# ============================================================
# 19. RESPONSE
# ============================================================

def respond_node(state: BuyerState):

    print("→ Response")

    substitution_item = state.get(
        "substitution_item"
    )

    selected_substitute = state.get(
        "selected_substitute"
    )

    # --------------------------------------------------------
    # Substitute suggestion
    # --------------------------------------------------------

    if (
        substitution_item
        and selected_substitute
    ):

        quantity = 1

        for item in state.get(
            "items",
            [],
        ):

            if (
                item.get(
                    "product_query",
                    ""
                ).lower()
                == substitution_item.lower()
            ):

                quantity = (
                    item.get(
                        "quantity"
                    )
                    or 1
                )

                break

        return {
            "final_response": (
                f"I couldn't satisfy your "
                f"{substitution_item} request. "
                f"I found a possible substitute: "
                f"{selected_substitute.get('name')} "
                f"× {quantity}. "
                f"Would you like me to use this "
                f"substitute?"
            )
        }

    # --------------------------------------------------------
    # Cart response
    # --------------------------------------------------------

    selected_offers = state.get(
        "selected_offers",
        [],
    )

    if selected_offers:

        lines = [
            (
                "Your cart is ready:"
                if state.get(
                    "cart_complete"
                )
                else
                "I found a partial cart, but some "
                "requested items are still missing:"
            )
        ]

        total = 0

        for offer in selected_offers:

            quantity = offer.get(
                "quantity",
                1,
            )

            price = offer.get(
                "price",
                0,
            )

            item_total = (
                price * quantity
            )

            total += item_total

            lines.append(
                f"- {offer.get('product_name')} "
                f"× {quantity} from "
                f"{offer.get('merchant')} "
                f"at ₹{price} each = "
                f"₹{item_total}"
            )

        lines.append(
            f"Cart total: ₹{total}"
        )

        if state.get(
            "cart_order_id"
        ):

            lines.append(
                f"Order: "
                f"{state['cart_order_id']}"
            )

        return {
            "final_response": (
                "\n".join(lines)
            )
        }

    # --------------------------------------------------------
    # Nothing found
    # --------------------------------------------------------

    return {
        "final_response": (
            "I could not find a suitable product "
            "that satisfies your requirements."
        )
    }


# ============================================================
# BUILD BUYER GRAPH
# ============================================================

def build_buyer_graph():

    graph = StateGraph(
        BuyerState
    )

    # ========================================================
    # NODES
    # ========================================================

    graph.add_node(
        "understand",
        understand,
    )

    graph.add_node(
        "build_shopping_goal",
        build_shopping_goal,
    )

    graph.add_node(
        "retrieve_product",
        retrieve_product,
    )

    graph.add_node(
        "relevance_gate",
        relevance_gate,
    )

    graph.add_node(
        "discover",
        discover,
    )

    graph.add_node(
        "query_merchants",
        query_merchants,
    )

    graph.add_node(
        "normalize_offers",
        normalize_offers_node,
    )

    graph.add_node(
        "evaluate_options",
        evaluate_options_node,
    )

    graph.add_node(
        "decide_substitution",
        decide_substitution_node,
    )

    graph.add_node(
        "select_substitute",
        select_substitute_node,
    )

    graph.add_node(
        "build_cart",
        build_cart_node,
    )

    graph.add_node(
        "validate",
        validate_node,
    )

    graph.add_node(
        "purchase",
        purchase_node,
    )

    graph.add_node(
        "respond",
        respond_node,
    )

    # ========================================================
    # MAIN FLOW
    # ========================================================

    graph.add_edge(
        START,
        "understand",
    )

    graph.add_edge(
        "understand",
        "build_shopping_goal",
    )

    graph.add_edge(
        "build_shopping_goal",
        "retrieve_product",
    )

    graph.add_edge(
        "retrieve_product",
        "relevance_gate",
    )

    # ========================================================
    # RELEVANCE
    # ========================================================

    graph.add_conditional_edges(
        "relevance_gate",
        route_after_relevance,
        {
            "discover": "discover",

            "decide_substitution": (
                "decide_substitution"
            ),
        },
    )

    # ========================================================
    # MERCHANT DISCOVERY
    # ========================================================

    graph.add_edge(
        "discover",
        "query_merchants",
    )

    # ========================================================
    # MERCHANT QUERY
    # ========================================================

    graph.add_edge(
        "query_merchants",
        "normalize_offers",
    )

    # ========================================================
    # NORMALIZATION
    # ========================================================

    graph.add_edge(
        "normalize_offers",
        "evaluate_options",
    )

    # ========================================================
    # EVALUATION
    # ========================================================

    graph.add_conditional_edges(
        "evaluate_options",
        route_after_evaluation,
        {
            "cart_complete": (
                "build_cart"
            ),

            "cart_incomplete": (
                "decide_substitution"
            ),
        },
    )

    # ========================================================
    # CART
    # ========================================================

    graph.add_edge(
        "build_cart",
        "validate",
    )

    # ========================================================
    # SUBSTITUTION DECISION
    # ========================================================

    graph.add_conditional_edges(
        "decide_substitution",
        route_after_substitution_decision,
        {
            "select_substitute": (
                "select_substitute"
            ),

            "respond": "respond",
        },
    )

    # ========================================================
    # SUBSTITUTE
    # ========================================================

    graph.add_conditional_edges(
        "select_substitute",
        route_after_substitute_selection,
        {
            "query_merchants": (
                "query_merchants"
            ),

            "respond": "respond",
        },
    )

    # ========================================================
    # VALIDATION
    # ========================================================

    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "purchase": "purchase",

            "respond": "respond",
        },
    )

    # ========================================================
    # PURCHASE
    # ========================================================

    graph.add_edge(
        "purchase",
        "respond",
    )

    # ========================================================
    # RESPONSE
    # ========================================================

    graph.add_edge(
        "respond",
        END,
    )

    return graph.compile()


# ============================================================
# COMPILED BUYER GRAPH
# ============================================================

buyer_graph = build_buyer_graph()
