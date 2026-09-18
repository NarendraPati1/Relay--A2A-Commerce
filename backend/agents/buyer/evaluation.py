def _effective_quantity(shopping_goal: dict, offer: dict) -> int:
    return int(
        offer.get("required_quantity")
        or shopping_goal.get("quantity")
        or 1
    )


def filter_valid_offers(
    offers: list[dict],
    shopping_goal: dict,
):
    valid_offers = []
    rejected_offers = []

    budget = shopping_goal.get("budget")
    explicit_quantity = shopping_goal.get("quantity")

    for offer in offers:
        reasons = []

        if not offer.get("available", False):
            reasons.append("not available")

        price = offer.get("price")
        quantity = _effective_quantity(shopping_goal, offer)

        # Budget is treated as a total budget when a multi-unit requirement
        # exists, otherwise as a unit-price ceiling.
        if budget is not None:
            if price is None:
                reasons.append("price unavailable")
            else:
                total = price * quantity
                if total > budget:
                    reasons.append(
                        f"estimated total ₹{total:g} exceeds budget ₹{budget:g}"
                    )

        stock = offer.get("stock")
        if explicit_quantity is not None or offer.get("required_quantity") is not None:
            if stock is None:
                reasons.append("stock unavailable")
            elif stock < quantity:
                reasons.append(
                    f"insufficient stock ({stock} available, {quantity} required)"
                )

        product_name = str(offer.get("product_name", "")).lower()
        merchant = str(offer.get("merchant", "")).lower()

        for constraint in shopping_goal.get("constraints", []):
            c = str(constraint).lower().strip()

            # Deterministic handling for explicit negative constraints.
            if any(word in c for word in ("avoid ", "exclude ", "not ", "no ")):
                banned = (
                    c.replace("avoid ", "")
                    .replace("exclude ", "")
                    .replace("not ", "")
                    .replace("no ", "")
                    .strip()
                )
                if banned and (banned in product_name or banned in merchant):
                    reasons.append(f"violates constraint: {constraint}")

        if reasons:
            valid = False
            rejected_offers.append({
                **offer,
                "rejection_reasons": reasons,
            })
        else:
            valid = True
            valid_offers.append({
                **offer,
                "effective_quantity": quantity,
                "estimated_total": (
                    price * quantity if price is not None else None
                ),
            })

    return valid_offers, rejected_offers


def evaluate_options(
    user_query: str,
    shopping_goal: dict,
    personalized_preferences: dict,
    normalized_offers: list[dict],
    requirement_plan: dict | None = None,
):
    valid_offers, rejected_offers = filter_valid_offers(
        normalized_offers,
        shopping_goal,
    )

    if not valid_offers:
        return {
            "valid_offers": [],
            "rejected_offers": rejected_offers,
            "selected_offer": None,
            "evaluation_reasoning": "No merchant offer satisfies the current hard constraints.",
        }

    # Price/stock/quantity are hard facts. Rank them deterministically to
    # keep ordinary carts fast and avoid model-rate-limit failures.
    preferred_brands = {
        str(shopping_goal.get("preferred_brand")).lower()
    } if shopping_goal.get("preferred_brand") else set()
    preferred_brands.update({
        str(brand).lower()
        for brand in personalized_preferences.get("preferred_brands", [])
    })
    def rank(offer: dict):
        product_brand = str(
            (offer.get("product") or {}).get("brand", "")
        ).lower()
        preferred_mismatch = bool(preferred_brands) and product_brand not in preferred_brands
        return (
            preferred_mismatch,
            offer.get("estimated_total") is None,
            offer.get("estimated_total") or float("inf"),
            -(offer.get("stock") or 0),
            str(offer.get("merchant", "")),
        )

    selected_offer = min(valid_offers, key=rank)

    return {
        "valid_offers": valid_offers,
        "rejected_offers": rejected_offers,
        "selected_offer": selected_offer,
        "evaluation_reasoning": (
            "Selected the lowest total among valid in-stock offers"
            + (" while honoring a saved brand preference." if preferred_brands else ".")
        ),
    }
