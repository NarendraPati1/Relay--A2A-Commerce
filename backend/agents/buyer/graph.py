from __future__ import annotations

import asyncio
import re
from typing import Any
from langgraph.graph import StateGraph, START, END

from agents.buyer.state import BuyerState, reset_for_new_request
from agents.buyer.security import safe_offer_for_model
from agents.buyer.llm import (
    buyer_intent_llm,
    shopping_goal_llm,
    requirement_planner_llm,
    buyer_response_llm,
)
from agents.buyer.discovery import discover_merchants
from agents.buyer.evaluation import evaluate_options
from agents.buyer.normalization import normalize_offers
from agents.buyer.substitution import decide_substitution, select_substitute
from agents.buyer.negotiation import decide_negotiation, negotiate_offer
from agents.buyer.relevance import check_relevance
from agents.buyer.a2a_client import ask_merchant
from agents.buyer.merchant_checkout import (
    create_merchant_payment_order, get_merchant_recommendations, verify_merchant_payment_a2a,
)
from agents.buyer.progress import report_agent_activity, report_progress

from retrieval.hybrid import search_products


# ============================================================
# 1. UNDERSTANDING
# ============================================================

_PAYMENT_CONFIRM_RE = re.compile(
    r"\b(yes|confirm|confirmed|approve|approved|proceed|go ahead|pay|payment|checkout|place order|make payment|confirm order)\b",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"\b(what|how|why|where|can|could|would|is|are|tell|explain|info)\b", re.IGNORECASE)

def is_payment_confirmation(query: str) -> bool:
    q = query.strip()
    if _QUESTION_RE.search(q):
        return False
    return bool(_PAYMENT_CONFIRM_RE.search(q))

def _previous_state_for_llm(state: BuyerState) -> dict:
    return {
        "intent": state.get("intent"),
        "conversation_action": state.get("conversation_action"),
        "quantity_planning_required": state.get(
            "quantity_planning_required", False
        ),
        "items": state.get("items", []),
        "shopping_goal": state.get("shopping_goal", {}),
        "cart": state.get("cart", {}),
        "cart_total": state.get("cart_total", 0),
        "cart_complete": state.get("cart_complete", False),
        "selected_offers": state.get("selected_offers", []),
        "validation_passed": state.get("validation_passed", False),
        "purchase_ready": state.get("purchase_ready", False),
        "awaiting_confirmation": state.get("awaiting_confirmation", False),
        "confirmation_type": state.get("confirmation_type"),
        "cart_order_id": state.get("cart_order_id"),
        "cart_payment_status": state.get("cart_payment_status"),
        "cart_order_status": state.get("cart_order_status"),
        "memory": state.get("memory_context", {}),
    }


def understand(state: BuyerState):
    report_progress("Understanding", "Reading your request and checking the conversation context.")

    query_str = (state.get("user_query") or "").strip()
    if re.match(r"^(hi|hello|hey|greetings|hola|good\s*(morning|afternoon|evening)|thanks|thank\s*you)[\.!\?]*$", query_str, re.IGNORECASE):
        patch = {
            "intent": "general",
            "conversation_action": "none",
            "items": [],
            "product_query": None,
            "quantity": None,
            "people_count": None,
            "duration_days": None,
            "budget": None,
            "brand_preference": None,
            "pack_size": None,
            "constraints": [],
        }
        patch.update(reset_for_new_request())
        return patch

    if (
        state.get("awaiting_confirmation")
        and state.get("confirmation_type") == "purchase"
        and is_payment_confirmation(query_str)
    ):
        return {
            "intent": "purchase",
            "conversation_action": "confirm",
            "items": state.get("items", []),
            "product_query": state.get("product_query"),
            "quantity": state.get("quantity"),
            "people_count": state.get("people_count"),
            "duration_days": state.get("duration_days"),
            "budget": state.get("budget"),
            "brand_preference": state.get("brand_preference"),
            "pack_size": state.get("pack_size"),
            "constraints": state.get("constraints", []),
        }

    result = buyer_intent_llm.invoke({
        "user_query": state["user_query"],
        "previous_state": _previous_state_for_llm(state),
    })

    raw_items = result.items or []  # type: ignore[union-attr]
    items: list[dict[str, Any]] = [item.model_dump() for item in raw_items]  # type: ignore[union-attr]

    # A genuinely new request should not accidentally retain purchase flags.
    conv_action: str = result.conversation_action  # type: ignore[union-attr]
    is_new_request = conv_action in {"new_request", "modify"}

    patch: dict[str, Any] = {
        "intent": result.intent,  # type: ignore[union-attr]
        "conversation_action": conv_action,
        "quantity_planning_required": result.quantity_planning_required,  # type: ignore[union-attr]
        "items": items,
        "product_query": items[0]["product_query"] if items else None,
        "quantity": items[0]["quantity"] if items else None,
        "people_count": items[0]["people_count"] if items else None,
        "duration_days": items[0]["duration_days"] if items else None,
        "budget": items[0]["budget"] if items else None,
        "brand_preference": (
            items[0]["brand_preference"] if items else None
        ),
        "pack_size": items[0]["pack_size"] if items else None,
        "constraints": items[0]["constraints"] if items else [],
    }

    if is_new_request:
        patch.update(reset_for_new_request())

    return patch


def route_after_understand(state: BuyerState):
    action = state.get("conversation_action")
    intent = state.get("intent")
    pending = state.get("awaiting_confirmation", False)

    # Code owns the consequential transition. The LLM only identifies
    # that the latest message is a confirmation.
    if pending:
        if (
            (action == "confirm" or intent == "purchase")
            and state.get("validation_passed")
            and state.get("confirmation_type") == "purchase"
        ):
            return "purchase"

        if action in {"decline", "question"}:
            return "respond"

        if action == "modify":
            return "shopping"

        # An unrecognized pending message should not purchase.
        return "respond"

    if intent == "general" or not state.get("items"):
        return "respond"

    return "shopping"


# ============================================================
# 2. SHOPPING GOAL
# ============================================================

def build_shopping_goal(state: BuyerState):
    report_progress("Clarifying your request", "Working out the products, quantities, budget, and preferences.")

    result = shopping_goal_llm.invoke({
        "user_query": state["user_query"],
        "buyer_intent": {
            "intent": state.get("intent"),
            "items": state.get("items", []),
        },
        "personalized_preferences": state.get(
            "personalized_preferences", {}
        ),
    })

    return {"shopping_goal": result.model_dump()}  # type: ignore[union-attr]


# ============================================================
# 3. PRODUCT DISCOVERY
# ============================================================

def retrieve_product(state: BuyerState):
    report_progress("Searching products", "Looking through the catalog for products that match your request.")

    item_candidates = {}
    all_candidates = []

    for item in state.get("items", []):
        query = item.get("product_query")
        if not query:
            continue

        report_progress("Searching products", f"Looking for “{query}”.")

        result = search_products(query=query, top_k=8)
        candidates = []

        for hit in result.get("candidates", []):
            product = hit["product"]
            candidate = {
                "id": product.get("id"),
                "name": product.get("name"),
                "description": product.get("description"),
                "category": product.get("category"),
                "brand": product.get("brand"),
                "pack_size": product.get("pack_size"),
                "exact_score": hit.get("exact_score"),
                "vector_score": hit.get("vector_score"),
                "rrf_score": hit.get("rrf_score"),
            }
            candidates.append(candidate)
            all_candidates.append(candidate)

        item_candidates[query] = candidates

    return {
        "item_candidates": item_candidates,
        "product_candidates": all_candidates,
    }


# ============================================================
# 4. REQUIREMENT PLANNING
# ============================================================

def _needs_requirement_planning(state: BuyerState) -> bool:
    """Use planning only when the request semantics require an estimate."""
    items = state.get("items", [])
    has_explicit_requirement = any(
        item.get("people_count") is not None
        or item.get("duration_days") is not None
        for item in items
    )
    return has_explicit_requirement or state.get(
        "quantity_planning_required", False
    )


def _align_requirement_plan(plan: dict, items: list[dict]) -> dict:
    """Recover omitted item labels only when their ordered pairing is known."""
    aligned = dict(plan)
    planned_items = [dict(item) for item in aligned.get("items", [])]
    if len(planned_items) == len(items):
        for index, planned_item in enumerate(planned_items):
            if not planned_item.get("product_query"):
                planned_item["product_query"] = items[index].get("product_query", "")
    aligned["items"] = planned_items
    return aligned


def plan_requirements_node(state: BuyerState):
    report_progress("Planning quantities", "Checking quantities and any product constraints.")

    # Unit quantities need no probabilistic serving estimate. Skipping this
    # model call keeps ordinary multi-item carts fast and inexpensive.
    if not _needs_requirement_planning(state):
        return {"requirement_plan": {"items": [
            {
                "product_query": item.get("product_query"),
                "people_count": None,
                "duration_days": None,
                "servings_per_person": None,
                "grams_per_serving": None,
                "reasoning_basis": "No people-based quantity estimate required.",
                "assumptions": [],
                "estimated_units_by_product_id": {},
            }
            for item in state.get("items", [])
        ]}}

    result = requirement_planner_llm.invoke({
        "user_query": state["user_query"],
        "shopping_goal": state.get("shopping_goal", {}),
        "buyer_intent": {
            "intent": state.get("intent"),
            "quantity_planning_required": state.get(
                "quantity_planning_required", False
            ),
            "items": state.get("items", []),
        },
        "product_candidates": state.get("product_candidates", []),
    })

    return {
        "requirement_plan": _align_requirement_plan(
            result.model_dump(), state.get("items", [])  # type: ignore[union-attr]
        )
    }


def _plan_for_item(state: BuyerState, item_query: str) -> dict:
    for item in state.get("requirement_plan", {}).get("items", []):
        if item.get("product_query", "").lower() == item_query.lower():
            return item
    return {}


def _apply_required_quantities(state: BuyerState):
    """
    Attach LLM-derived estimated quantities to offers/candidates.

    The estimate is explicitly marked as such. Merchant stock is still
    authoritative for whether that quantity is actually available.
    """
    plan_items = state.get("requirement_plan", {}).get("items", [])
    by_query = {
        p.get("product_query", "").lower(): p
        for p in plan_items
    }

    for candidate in state.get("product_candidates", []):
        query = candidate.get("source_query")
        if not query:
            continue
        plan = by_query.get(query.lower(), {})
        units = plan.get("estimated_units_by_product_id", {})
        cid = str(candidate.get("id"))
        if cid in units:
            candidate["estimated_required_quantity"] = units[cid]

    return by_query


# ============================================================
# 5. RELEVANCE
# ============================================================

def relevance_gate(state: BuyerState):
    report_progress("Checking matches", "Removing products that do not meet your request.")

    item_relevance = {}
    all_relevant = []
    all_rejected = []

    for item in state.get("items", []):
        query = item.get("product_query")
        if not isinstance(query, str):
            continue
        candidates: list[dict[str, Any]] = state.get("item_candidates", {}).get(query, [])

        plan = _plan_for_item(state, query)

        item_goal = {
            "product": query,
            "quantity": item.get("quantity"),
            "people_count": item.get("people_count"),
            "duration_days": item.get("duration_days"),
            "budget": item.get("budget"),
            "preferred_brand": item.get("brand_preference"),
            "preferred_pack_size": item.get("pack_size"),
            "constraints": item.get("constraints", []),
            "requirement_plan": plan,
        }

        relevant, rejected = check_relevance(
            user_query=state["user_query"],
            shopping_goal=item_goal,
            product_candidates=candidates,
        )

        # Preserve candidate-specific requirement estimates.
        units = plan.get("estimated_units_by_product_id", {})
        for c in relevant + rejected:
            cid = str(c.get("id"))
            if cid in units:
                c["estimated_required_quantity"] = units[cid]

        item_relevance[query] = {
            "relevant": relevant,
            "rejected": rejected,
        }

        all_relevant.extend(relevant)
        all_rejected.extend(rejected)

    return {
        "item_relevance": item_relevance,
        "relevant_product_candidates": all_relevant,
        "irrelevant_product_candidates": all_rejected,
    }


def route_after_relevance(state: BuyerState):
    for result in state.get("item_relevance", {}).values():
        if result.get("relevant"):
            return "discover"
    return "decide_substitution"


# ============================================================
# 6. MERCHANT DISCOVERY
# ============================================================

async def discover(state: BuyerState):
    report_progress("Finding merchants", "Checking which merchants are currently available.")
    report_agent_activity(
        "Buyer agent", "Marketplace", "Looking for available merchant agents.",
    )
    merchants = await discover_merchants()
    merchant_names = [str(merchant.get("name", "Merchant agent")) for merchant in merchants]
    if merchant_names:
        report_agent_activity(
            "Marketplace", "Buyer agent",
            f"Connected {len(merchant_names)} merchant agent{'s' if len(merchant_names) != 1 else ''} for this request.",
            merchants=merchant_names,
        )
    else:
        report_agent_activity(
            "Marketplace", "Buyer agent",
            "No merchant agents are reachable right now.", merchants=[],
        )
    report_progress(
        "Merchants ready",
        f"{len(merchants)} merchant{'s are' if len(merchants) != 1 else ' is'} available for this request.",
    )
    return {"merchants": merchants}


# ============================================================
# 7. A2A MERCHANT QUERY
# ============================================================

async def _query_one_merchant(
    item_query: str,
    product: dict,
    merchant: dict,
):
    response = await ask_merchant(
        query=product.get("name", ""),
        merchant_url=merchant["agent_url"],
    )

    return {
        "item_query": item_query,
        "merchant": merchant["name"],
        "merchant_url": merchant["agent_url"],
        "product": product,
        "response": response,
    }


async def query_merchants(state: BuyerState):
    report_progress("Requesting offers", "Asking available merchants for current price and stock.")

    merchant_names = [str(merchant.get("name", "Merchant agent")) for merchant in state.get("merchants", [])]
    if merchant_names:
        report_agent_activity(
            "Buyer agent", "Merchant agents",
            "Please share your current availability and price for the matching products.",
            merchants=merchant_names,
        )

    tasks = []

    for item in state.get("items", []):
        query = item.get("product_query")
        if not query:
            continue

        relevance = state.get("item_relevance", {}).get(query, {})
        candidates = list(relevance.get("relevant", []))

        substitution = state.get("item_substitutions", {}).get(query, {})
        selected_substitute = substitution.get("selected_substitute")

        if selected_substitute:
            candidates = [selected_substitute]

        for merchant in state.get("merchants", []):
            for product in candidates:
                tasks.append(
                    _query_one_merchant(query, product, merchant)
                )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    offers = []
    for result in results:
        if isinstance(result, Exception):
            report_progress("Merchant unavailable", "One merchant could not be reached, so I’m continuing with the available offers.")
            continue
        offers.append(result)

    if offers:
        responding_merchants = sorted({str(offer.get("merchant", "Merchant agent")) for offer in offers})
        report_agent_activity(
            "Merchant agents", "Buyer agent",
            f"We returned {len(offers)} current offer{'s' if len(offers) != 1 else ''} for comparison.",
            merchants=responding_merchants,
        )

    report_progress("Offers received", f"Received {len(offers)} current merchant offers to compare.")

    item_offers = {}
    for offer in offers:
        item_offers.setdefault(
            offer["item_query"], []
        ).append(offer)

    return {
        "item_offers": item_offers,
        "merchant_offers": offers,
        "normalized_offers": [],
        "valid_offers": [],
        "rejected_offers": [],
        "selected_offer": None,
        "selected_offers": [],
        "item_evaluations": {},
    }


# ============================================================
# 8. NORMALIZATION
# ============================================================

def normalize_offers_node(state: BuyerState):
    report_progress("Standardizing offers", "Putting merchant offers into the same format for a fair comparison.")

    normalized = normalize_offers(
        state.get("merchant_offers", [])
    )

    # Attach product metadata and requirement estimates.
    by_query = {
        x.get("product_query", "").lower(): x
        for x in state.get("items", [])
    }

    for offer in normalized:
        query = offer.get("item_query", "")
        item = by_query.get(query.lower(), {})
        plan = _plan_for_item(state, query)

        units = plan.get("estimated_units_by_product_id", {})
        pid = str(offer.get("product_id"))

        if item.get("quantity") is not None:
            offer["required_quantity"] = item["quantity"]
        elif pid in units:
            offer["required_quantity"] = units[pid]
            offer["quantity_is_estimated"] = True
        else:
            offer["required_quantity"] = 1
            offer["quantity_is_estimated"] = False

        offer["people_count"] = plan.get("people_count")
        offer["duration_days"] = plan.get("duration_days") or item.get("duration_days")
        offer["servings_per_person"] = plan.get("servings_per_person")
        offer["grams_per_serving"] = plan.get("grams_per_serving")
        offer["requirement_assumptions"] = plan.get("assumptions", [])

    item_normalized = {}
    for offer in normalized:
        item_normalized.setdefault(
            offer.get("item_query"), []
        ).append(offer)

    return {
        "item_normalized_offers": item_normalized,
        "normalized_offers": normalized,
    }


# ============================================================
# 9. EVALUATION
# ============================================================

def evaluate_options_node(state: BuyerState):
    report_progress("Comparing options", "Comparing price, availability, and how well each offer fits your request.")

    item_evaluations = {}
    selected_offers = []
    all_valid = []
    all_rejected = []

    for item in state.get("items", []):
        query = item.get("product_query")
        if not isinstance(query, str):
            continue
        offers = state.get(
            "item_normalized_offers", {}
        ).get(query, [])

        goal_item = {
            "product": query,
            "quantity": item.get("quantity"),
            "people_count": item.get("people_count"),
            "duration_days": item.get("duration_days"),
            "budget": item.get("budget"),
            "preferred_brand": item.get("brand_preference"),
            "preferred_pack_size": item.get("pack_size"),
            "constraints": item.get("constraints", []),
        }

        # Merge richer shopping-goal information if available.
        for goal_item2 in state.get("shopping_goal", {}).get("items", []):
            if isinstance(goal_item2, dict) and str(goal_item2.get("product", "")).lower() == query.lower():
                goal_item.update(goal_item2)
                break

        plan = _plan_for_item(state, query)

        result = evaluate_options(
            user_query=state["user_query"],
            shopping_goal=goal_item,
            personalized_preferences=state.get(
                "personalized_preferences", {}
            ),
            normalized_offers=offers,
            requirement_plan=plan,
        )

        selected = result.get("selected_offer")
        if selected and isinstance(selected, dict):
            selected = dict(selected)
            selected["item_query"] = query
            selected_offers.append(selected)

        item_evaluations[query] = result
        valid_offers_chunk = result.get("valid_offers", []) or []
        rejected_offers_chunk = result.get("rejected_offers", []) or []
        all_valid.extend(valid_offers_chunk if isinstance(valid_offers_chunk, list) else [])
        all_rejected.extend(rejected_offers_chunk if isinstance(rejected_offers_chunk, list) else [])

    return {
        "item_evaluations": item_evaluations,
        "selected_offers": selected_offers,
        "valid_offers": all_valid,
        "rejected_offers": all_rejected,
        "selected_offer": (
            selected_offers[0] if selected_offers else None
        ),
        "evaluation_reasoning": "; ".join(
            str(v.get("evaluation_reasoning", ""))
            for v in item_evaluations.values()
            if v.get("evaluation_reasoning")
        ),
    }


def route_after_evaluation(state: BuyerState):
    return (
        "cart_complete"
        if len(state.get("selected_offers", []))
        == len(state.get("items", []))
        else "cart_incomplete"
    )


# ============================================================
# 10. NEGOTIATION
# ============================================================

async def negotiate_selected_offers_node(state: BuyerState):
    report_progress("Checking eligible prices", "Seeing whether the selected offers qualify for a better price.")

    selected = state.get("selected_offers", [])
    negotiated = []

    for offer in selected:
        query = offer.get("item_query")
        item = next(
            (
                x for x in state.get("items", [])
                if x.get("product_query") == query
            ),
            {},
        )

        goal = {
            "product": query,
            "quantity": offer.get("required_quantity"),
            "people_count": item.get("people_count"),
            "duration_days": item.get("duration_days"),
            "budget": item.get("budget"),
            "preferred_brand": item.get("brand_preference"),
            "preferred_pack_size": item.get("pack_size"),
            "constraints": item.get("constraints", []),
        }

        decision = decide_negotiation(
            user_query=state["user_query"],
            shopping_goal=goal,
            selected_offer=offer,
        )

        if decision["negotiation_requested"]:
            result = await negotiate_offer(offer, goal)

            if (
                result.get("accepted")
                and result.get("effective_unit_price") is not None
            ):
                offer = {
                    **offer,
                    "original_price": offer.get("price"),
                    "price": result["effective_unit_price"],
                    "negotiated": True,
                    "negotiation": result,
                }

        negotiated.append(offer)

    return {
        "selected_offers": negotiated,
        "selected_offer": negotiated[0] if negotiated else None,
        "negotiation_requested": any(
            o.get("negotiated") for o in negotiated
        ),
        "negotiation_result": (
            next(
                (
                    o.get("negotiation")
                    for o in negotiated
                    if o.get("negotiation")
                ),
                None,
            )
        ),
    }


async def merchant_recommendations_node(state: BuyerState):
    """Retrieve merchant suggestions as optional evidence, never cart items."""
    report_progress("Checking optional suggestions", "Looking for relevant optional items. They will not be added automatically.")
    results = await asyncio.gather(
        *(get_merchant_recommendations(offer) for offer in state.get("selected_offers", [])),
        return_exceptions=True,
    )
    recommendations = []
    for result in results:
        if not isinstance(result, Exception) and isinstance(result, list):
            recommendations.extend(result)
    return {"merchant_recommendations": recommendations}


# ============================================================
# 11. SUBSTITUTION
# ============================================================

def _item_goal(state: BuyerState, query: str) -> dict:
    for item in state.get("shopping_goal", {}).get("items", []):
        if str(item.get("product", "")).lower() == query.lower():
            return item

    for item in state.get("items", []):
        if item.get("product_query") == query:
            return {
                "product": query,
                "quantity": item.get("quantity"),
                "people_count": item.get("people_count"),
                "duration_days": item.get("duration_days"),
                "budget": item.get("budget"),
                "preferred_brand": item.get("brand_preference"),
                "preferred_pack_size": item.get("pack_size"),
                "constraints": item.get("constraints", []),
            }

    return {"product": query}


def decide_substitution_node(state: BuyerState):
    report_progress("Considering alternatives", "Checking whether a suitable alternative is available.")

    history = dict(state.get("item_substitutions", {}))

    for item in state.get("items", []):
        query = item.get("product_query")
        if not isinstance(query, str):
            continue
        evaluation = state.get(
            "item_evaluations", {}
        ).get(query, {})

        if evaluation.get("selected_offer"):
            continue

        previous = dict(history.get(query, {}))
        attempted = previous.get("attempted_product_ids", [])

        relevance = state.get("item_relevance", {}).get(query, {})
        candidates = (
            relevance.get("relevant", [])
            + relevance.get("rejected", [])
        )

        result = decide_substitution(
            user_query=state["user_query"],
            original_product=query,
            product_candidates=candidates,
            shopping_goal=_item_goal(state, query),
            personalized_preferences=state.get(
                "personalized_preferences", {}
            ),
            rejected_offers=evaluation.get(
                "rejected_offers", []
            ),
            attempted_product_ids=attempted,
        )

        if result.get("substitution_requested"):
            return {
                "substitution_requested": True,
                "substitution_item": query,
                "substitution_reasoning": result.get(
                    "substitution_reasoning", ""
                ),
                "substitute_candidates": result.get(
                    "candidates", []
                ),
            }

    return {
        "substitution_requested": False,
        "substitution_item": None,
        "substitution_reasoning": "No useful substitution is available.",
    }


def route_after_substitution_decision(state: BuyerState):
    return (
        "select_substitute"
        if state.get("substitution_requested")
        else "respond"
    )


def select_substitute_node(state: BuyerState):
    report_progress("Selecting an alternative", "Choosing the closest available alternative for review.")

    query = state.get("substitution_item")
    if not query:
        return {"selected_substitute": None}

    history_all = dict(state.get("item_substitutions", {}))
    history = dict(history_all.get(query, {}))

    attempted = list(history.get("attempted_product_ids", []))

    result = select_substitute(
        user_query=state["user_query"],
        original_product=query,
        product_candidates=state.get(
            "substitute_candidates",
            state.get("item_candidates", {}).get(query, [])
        ),
        shopping_goal=_item_goal(state, query),
        personalized_preferences=state.get(
            "personalized_preferences", {}
        ),
        rejected_offers=state.get(
            "item_evaluations", {}
        ).get(query, {}).get("rejected_offers", []),
        attempted_product_ids=attempted,
    )

    selected = result.get("selected_substitute")
    if selected and isinstance(selected, dict):
        sid = selected.get("id")
        if sid and sid not in attempted:
            attempted.append(sid)

    history.update({
        "requested": True,
        "selected_substitute": selected,
        "reasoning": result.get("substitution_reasoning", ""),
        "attempted_product_ids": attempted,
        "attempt_count": len(attempted),
    })
    history_all[query] = history

    return {
        "selected_substitute": selected,
        "substitution_reasoning": result.get(
            "substitution_reasoning", ""
        ),
        "item_substitutions": history_all,
    }


def route_after_substitute_selection(state: BuyerState):
    return (
        "query_merchants"
        if state.get("selected_substitute")
        else "respond"
    )


# ============================================================
# 12. CART
# ============================================================

def build_cart_node(state: BuyerState):
    report_progress("Building your cart", "Adding the best verified offers to a reviewable cart.")

    items = []

    for offer in state.get("selected_offers", []):
        quantity = (
            offer.get("effective_quantity")
            or offer.get("required_quantity")
            or 1
        )
        price = offer.get("price")

        if price is None:
            continue

        items.append({
            "item_query": offer.get("item_query"),
            "product_name": offer.get("product_name"),
            "merchant": offer.get("merchant"),
            "merchant_url": offer.get("merchant_url"),
            "quantity": quantity,
            "quantity_is_estimated": bool(
                offer.get("quantity_is_estimated", False)
            ),
            "unit_price": price,
            "total_price": price * quantity,
            "product": offer.get("product"),
            "requirement_assumptions": offer.get(
                "requirement_assumptions", []
            ),
            "people_count": offer.get("people_count"),
            "duration_days": offer.get("duration_days"),
            "servings_per_person": offer.get(
                "servings_per_person"
            ),
            "grams_per_serving": offer.get(
                "grams_per_serving"
            ),
            "negotiated": offer.get("negotiated", False),
        })

    total = sum(x["total_price"] for x in items)

    return {
        "cart": {
            "items": items,
            "total": total,
            "item_count": len(items),
            "complete": (
                len(items) == len(state.get("items", []))
            ),
        },
        "cart_total": total,
        "cart_complete": (
            len(items) == len(state.get("items", []))
        ),
    }


# ============================================================
# 13. VALIDATION
# ============================================================

def validate_node(state: BuyerState):
    report_progress("Validating the cart", "Checking the selected prices and cart details before showing results.")

    validations = {}

    for cart_item in state.get("cart", {}).get("items", []):
        query = cart_item.get("item_query")
        quantity = cart_item.get("quantity", 1)

        offer = next(
            (
                x for x in state.get("selected_offers", [])
                if x.get("item_query") == query
            ),
            {},
        )

        stock = offer.get("stock")
        price = offer.get("price")

        item = next(
            (
                x for x in state.get("items", [])
                if x.get("product_query") == query
            ),
            {},
        )

        budget = item.get("budget")
        stock_valid = stock is not None and stock >= quantity

        # Budget here is a total cart/item budget.
        price_valid = (
            price is not None
            and (
                budget is None
                or price * quantity <= budget
            )
        )

        constraints_valid = True
        product_name = str(
            offer.get("product_name", "")
        ).lower()
        merchant = str(
            offer.get("merchant", "")
        ).lower()

        for constraint in item.get("constraints", []):
            c = str(constraint).lower().strip()
            if any(x in c for x in ("avoid ", "exclude ", "not ", "no ")):
                banned = (
                    c.replace("avoid ", "")
                    .replace("exclude ", "")
                    .replace("not ", "")
                    .replace("no ", "")
                    .strip()
                )
                if banned and (
                    banned in product_name
                    or banned in merchant
                ):
                    constraints_valid = False

        validations[query] = {
            "stock_valid": stock_valid,
            "price_valid": price_valid,
            "constraints_valid": constraints_valid,
            "validation_passed": (
                stock_valid
                and price_valid
                and constraints_valid
            ),
        }

    passed = (
        bool(state.get("items"))
        and len(validations) == len(state.get("items", []))
        and all(x["validation_passed"] for x in validations.values())
    )

    return {
        "item_validations": validations,
        "stock_valid": (
            bool(validations)
            and all(x["stock_valid"] for x in validations.values())
        ),
        "price_valid": (
            bool(validations)
            and all(x["price_valid"] for x in validations.values())
        ),
        "constraints_valid": (
            bool(validations)
            and all(x["constraints_valid"] for x in validations.values())
        ),
        "validation_passed": passed,
        "purchase_ready": passed,
    }


def route_after_validation(state: BuyerState):
    if state.get("validation_passed"):
        return "confirm_purchase"

    return "respond"


# ============================================================
# 14. CONFIRMATION
# ============================================================

def await_purchase_confirmation(state: BuyerState):
    report_progress("Waiting for approval", "Your cart is ready. A payment order will only be created after you approve it.")

    cart_items = state.get("cart", {}).get("items", [])
    lines = ["I’ve prepared this cart:"]
    for item in cart_items:
        quantity = item.get("quantity", 1)
        total = item.get("total_price")
        price_text = f"₹{total:g}" if isinstance(total, (int, float)) else "the quoted price"
        lines.append(
            f"- {item.get('product_name')} × {quantity} from "
            f"{item.get('merchant')} — {price_text}"
        )
    total = state.get("cart_total", 0)
    if isinstance(total, (int, float)):
        lines.append(f"Total: ₹{total:g}.")
    lines.append("Please confirm if you want me to create the payment order.")

    return {
        "awaiting_confirmation": True,
        "confirmation_type": "purchase",
        "user_confirmation": None,
        "purchase_ready": False,
        "final_response": "\n".join(lines),
    }


# ============================================================
# 15. PURCHASE
# ============================================================

async def purchase_node(state: BuyerState):
    report_progress("Creating secure payment", "Asking the selected merchant to create the payment order you approved.")

    if not state.get("validation_passed"):
        return {
            "purchase_ready": False,
            "cart_payment_status": "not_started",
            "cart_order_status": "not_created",
        }

    # Payment is an explicit, idempotent state transition—not an LLM action.
    if (
        not state.get("awaiting_confirmation")
        or state.get("confirmation_type") != "purchase"
        or not state.get("selected_offers")
        or float(state.get("cart_total", 0)) <= 0
    ):
        return {
            "purchase_ready": False,
            "cart_payment_status": "not_started",
            "cart_order_status": "not_created",
        }

    if state.get("razorpay_order_id"):
        return {
            "purchase_ready": True,
            "cart_order_id": state["razorpay_order_id"],
            "cart_payment_status": state.get("cart_payment_status") or "pending",
            "cart_order_status": state.get("cart_order_status") or "created",
        }

    # Each merchant owns the transaction and Razorpay test order. The buyer
    # orchestrates the approved checkout over A2A; it never creates payment
    # orders directly.
    orders = []
    for offer in state.get("selected_offers", []):
        order = await create_merchant_payment_order(
            offer=offer,
            session_id=str(state.get("session_id", "")),
            buyer_reference=str(state.get("buyer_id", "")),
        )
        if order is None:
            return {
                "purchase_ready": False,
                "cart_payment_status": "payment_order_failed",
                "cart_order_status": "not_created",
                "merchant_payment_orders": orders,
            }
        
        # Buyer Agent automatically settles payment via A2A protocol
        verified = await verify_merchant_payment_a2a(order)
        if verified:
            order["status"] = "verified"
            order["paid_by_agent"] = True
        orders.append(order)

    order_id = orders[0]["razorpay_order_id"] if len(orders) == 1 else None
    all_verified = all(o.get("status") == "verified" for o in orders)

    return {
        "purchase_ready": True,
        "awaiting_confirmation": False,
        "user_confirmation": "yes",
        "confirmation_type": "purchase",
        "cart_order_id": order_id,
        "razorpay_order_id": order_id,
        "cart_payment_status": "verified" if all_verified else "pending",
        "cart_order_status": "completed" if all_verified else "created",
        "merchant_payment_orders": orders,
    }


# ============================================================
# 16. RESPONSE
# ============================================================

def respond_node(state: BuyerState):
    report_progress("Preparing your results", "Writing a clear summary of the verified options and next step.")

    # A pending purchase is a consequential state. Generate its summary from
    # validated cart facts instead of allowing a conversational model to echo
    # stale messages from an earlier turn.
    if state.get("awaiting_confirmation"):
        cart_items = state.get("cart", {}).get("items", [])
        lines = ["I’ve prepared this cart:"]
        for item in cart_items:
            quantity = item.get("quantity", 1)
            total = item.get("total_price")
            price_text = f"₹{total:g}" if isinstance(total, (int, float)) else "the quoted price"
            lines.append(
                f"- {item.get('product_name')} × {quantity} from "
                f"{item.get('merchant')} — {price_text}"
            )
        total = state.get("cart_total", 0)
        if isinstance(total, (int, float)):
            lines.append(f"Total: ₹{total:g}.")
        lines.append("Please confirm if you want me to create the payment order.")
        return {"final_response": "\n".join(lines)}

    # Do not let a general-purpose response model imply that an unavailable
    # product can be sourced. This is based on catalog/merchant evidence.
    requested_items = state.get("items", [])
    has_no_matching_offer = (
        bool(requested_items)
        and not state.get("selected_offers")
        and not state.get("awaiting_confirmation")
        and not state.get("cart_order_id")
    )
    if has_no_matching_offer:
        requested = ", ".join(
            str(item.get("product_query"))
            for item in requested_items
            if item.get("product_query")
        )
        return {
            "final_response": (
                f"I don’t currently have a verified catalog or merchant offer for {requested}. "
                "I can only recommend items with an available, verified offer."
            )
        }

    # Keep the final model prompt small. Raw retrieval hits, full merchant
    # prose, and every rejected offer are neither necessary nor safe to echo.
    context = {
        "intent": state.get("intent"),
        "items": state.get("items", []),
        "selected_offers": [
            safe_offer_for_model(offer)
            for offer in state.get("selected_offers", [])
        ],
        "cart": state.get("cart", {}),
        "cart_complete": state.get("cart_complete", False),
        "evaluation_reasoning": state.get("evaluation_reasoning"),
        "substitution_requested": state.get("substitution_requested", False),
        "substitution_reasoning": state.get("substitution_reasoning"),
        "selected_substitute": state.get("selected_substitute"),
        "awaiting_confirmation": state.get("awaiting_confirmation", False),
        "confirmation_type": state.get("confirmation_type"),
        "purchase_ready": state.get("purchase_ready", False),
        "cart_order_id": state.get("cart_order_id"),
        "cart_payment_status": state.get("cart_payment_status"),
        "cart_order_status": state.get("cart_order_status"),
        "merchant_recommendations": state.get("merchant_recommendations", []),
        "memory": state.get("memory_context", {}),
    }

    result = buyer_response_llm.invoke({
        "user_query": state.get("user_query", ""),
        "context": context,
    })

    return {"final_response": result.response}  # type: ignore[union-attr]


# ============================================================
# 17. GRAPH
# ============================================================

def build_buyer_graph():
    graph = StateGraph(BuyerState)  # type: ignore[type-var]

    graph.add_node("understand", understand)
    graph.add_node("build_shopping_goal", build_shopping_goal)
    graph.add_node("retrieve_product", retrieve_product)
    graph.add_node("plan_requirements", plan_requirements_node)
    graph.add_node("relevance_gate", relevance_gate)
    graph.add_node("discover", discover)
    graph.add_node("query_merchants", query_merchants)
    graph.add_node("normalize_offers", normalize_offers_node)
    graph.add_node("evaluate_options", evaluate_options_node)
    graph.add_node("negotiate", negotiate_selected_offers_node)
    graph.add_node("merchant_recommendations", merchant_recommendations_node)
    graph.add_node("decide_substitution", decide_substitution_node)
    graph.add_node("select_substitute", select_substitute_node)
    graph.add_node("build_cart", build_cart_node)
    graph.add_node("validate", validate_node)
    graph.add_node("await_purchase_confirmation", await_purchase_confirmation)
    graph.add_node("purchase", purchase_node)
    graph.add_node("respond", respond_node)

    graph.add_edge(START, "understand")

    graph.add_conditional_edges(
        "understand",
        route_after_understand,
        {
            "shopping": "build_shopping_goal",
            "respond": "respond",
            "purchase": "purchase",
        },
    )

    graph.add_edge("build_shopping_goal", "retrieve_product")
    graph.add_edge("retrieve_product", "plan_requirements")
    graph.add_edge("plan_requirements", "relevance_gate")

    graph.add_conditional_edges(
        "relevance_gate",
        route_after_relevance,
        {
            "discover": "discover",
            "decide_substitution": "decide_substitution",
        },
    )

    graph.add_edge("discover", "query_merchants")
    graph.add_edge("query_merchants", "normalize_offers")
    graph.add_edge("normalize_offers", "evaluate_options")

    graph.add_conditional_edges(
        "evaluate_options",
        route_after_evaluation,
        {
            "cart_complete": "negotiate",
            "cart_incomplete": "decide_substitution",
        },
    )

    graph.add_edge("negotiate", "merchant_recommendations")
    graph.add_edge("merchant_recommendations", "build_cart")

    graph.add_conditional_edges(
        "decide_substitution",
        route_after_substitution_decision,
        {
            "select_substitute": "select_substitute",
            "respond": "respond",
        },
    )

    graph.add_conditional_edges(
        "select_substitute",
        route_after_substitute_selection,
        {
            "query_merchants": "query_merchants",
            "respond": "respond",
        },
    )

    graph.add_edge("build_cart", "validate")

    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "confirm_purchase": "await_purchase_confirmation",
            "respond": "respond",
        },
    )

    graph.add_edge("await_purchase_confirmation", END)
    graph.add_edge("purchase", "respond")
    graph.add_edge("respond", END)

    return graph.compile()


buyer_graph = build_buyer_graph()
