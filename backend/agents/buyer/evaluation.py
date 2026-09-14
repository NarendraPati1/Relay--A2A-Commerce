from agents.buyer.llm import option_evaluator_llm


def filter_valid_offers(
    offers: list[dict],
    shopping_goal: dict,
):
    valid_offers = []
    rejected_offers = []

    budget = shopping_goal.get("budget")
    quantity = shopping_goal.get("quantity")
    preferred_brand = shopping_goal.get("preferred_brand")
    constraints = shopping_goal.get("constraints", [])

    for offer in offers:

        reasons = []

        # ---------------------------------------------
        # Availability
        # ---------------------------------------------

        if not offer.get("available", False):
            reasons.append("not available")

        # ---------------------------------------------
        # Price
        # ---------------------------------------------

        price = offer.get("price")

        if budget is not None:

            if price is None:
                reasons.append("price unavailable")

            elif price > budget:
                reasons.append(
                    f"price ₹{price} exceeds budget ₹{budget}"
                )

        # ---------------------------------------------
        # Quantity / stock
        # ---------------------------------------------

        stock = offer.get("stock")

        if quantity is not None:

            if stock is None:
                reasons.append("stock unavailable")

            elif stock < quantity:
                reasons.append(
                    f"insufficient stock ({stock} available, "
                    f"{quantity} requested)"
                )

        # ---------------------------------------------
        # Explicit exclusions
        # ---------------------------------------------

        product_name = offer["product_name"].lower()
        merchant = offer["merchant"].lower()

        for constraint in constraints:

            constraint_lower = constraint.lower()

            # Basic exclusion handling
            if (
                "not" in constraint_lower
                or "exclude" in constraint_lower
                or "avoid" in constraint_lower
            ):
                words = constraint_lower.replace(
                    "not", ""
                ).replace(
                    "exclude", ""
                ).replace(
                    "avoid", ""
                ).strip()

                if words and (
                    words in product_name
                    or words in merchant
                ):
                    reasons.append(
                        f"violates constraint: {constraint}"
                    )

        # ---------------------------------------------
        # Result
        # ---------------------------------------------

        if reasons:

            rejected_offers.append({
                **offer,
                "rejection_reasons": reasons,
            })

        else:

            valid_offers.append(offer)

    return valid_offers, rejected_offers


def evaluate_options(
    user_query: str,
    shopping_goal: dict,
    personalized_preferences: dict,
    normalized_offers: list[dict],
):
    # ---------------------------------------------
    # 1. Deterministic hard filtering
    # ---------------------------------------------

    valid_offers, rejected_offers = filter_valid_offers(
        normalized_offers,
        shopping_goal,
    )

    # ---------------------------------------------
    # 2. No valid offers
    # ---------------------------------------------

    if not valid_offers:

        return {
            "valid_offers": [],
            "rejected_offers": rejected_offers,
            "selected_offer": None,
            "evaluation_reasoning": (
                "No merchant offer satisfies the "
                "customer's current constraints."
            ),
        }

    # ---------------------------------------------
    # 3. LLM preference evaluation
    # ---------------------------------------------

    result = option_evaluator_llm.invoke({
        "user_query": user_query,
        "shopping_goal": shopping_goal,
        "personalized_preferences": personalized_preferences,
        "valid_offers": valid_offers,
    })

    selected_offer = None

    if result.selected_offer_index is not None:

        index = result.selected_offer_index

        if 0 <= index < len(valid_offers):
            selected_offer = valid_offers[index]

    return {
        "valid_offers": valid_offers,
        "rejected_offers": rejected_offers,
        "selected_offer": selected_offer,
        "evaluation_reasoning": result.reasoning,
    }
