from agents.buyer.llm import (
    substitution_decision_llm,
    substitute_selector_llm,
)


# ============================================================
# HELPERS
# ============================================================

def _normalize(value: str | None) -> str:
    if not value:
        return ""

    return " ".join(
        value.lower().strip().split()
    )


def _is_exact_only_request(
    user_query: str,
) -> bool:

    query = _normalize(user_query)

    exact_only_phrases = [
        "exact product",
        "exact item",
        "only this",
        "only this product",
        "no substitute",
        "no substitutes",
        "do not substitute",
        "don't substitute",
        "dont substitute",
        "nothing else",
    ]

    return any(
        phrase in query
        for phrase in exact_only_phrases
    )


def _get_product_id(candidate: dict) -> str:
    return _normalize(
        candidate.get("product_id")
        or candidate.get("id")
    )


def _get_product_name(candidate: dict) -> str:
    return _normalize(
        candidate.get("product_name")
        or candidate.get("name")
    )


def _is_same_product(
    candidate: dict,
    original_product: str,
) -> bool:
    """
    Prevent the original failed product from being
    selected again as its own substitute.
    """

    candidate_name = _get_product_name(candidate)
    candidate_id = _get_product_id(candidate)
    original = _normalize(original_product)

    # Strong signal: exact retrieval match.
    exact_score = candidate.get("exact_score")

    if exact_score is not None:
        try:
            if float(exact_score) >= 0.8:
                return True
        except (TypeError, ValueError):
            pass

    # Exact ID/query match.
    if candidate_id and original and candidate_id == original:
        return True

    # Exact name/query match.
    if candidate_name and original and candidate_name == original:
        return True

    # Example:
    # original = "nescafe"
    # candidate = "nescafe classic 100g"
    #
    # Do not offer the same product family as a substitute.
    if original and candidate_name and original in candidate_name:
        return True

    return False


def _candidate_relationship(
    candidate: dict,
    original_category: str | None = None,
    preferred_brand: str | None = None,
) -> int:
    """
    Relationship priority:

    1 = same preferred brand
    2 = same category
    3 = closely related category
    4 = unrelated

    Lower number = better substitute.
    """

    candidate_brand = _normalize(
        candidate.get("brand")
    )

    preferred_brand = _normalize(
        preferred_brand
        or candidate.get("preferred_brand")
    )

    candidate_category = _normalize(
        candidate.get("category")
    )

    original_category = _normalize(
        original_category
        or candidate.get("original_category")
    )

    # Same preferred brand.
    if (
        preferred_brand
        and candidate_brand
        and candidate_brand == preferred_brand
    ):
        return 1

    # Same category.
    if (
        original_category
        and candidate_category
        and candidate_category == original_category
    ):
        return 2

    # Closely related categories.
    related_categories = {
        "coffee": {
            "coffee",
            "instant coffee",
            "filter coffee",
            "ground coffee",
        },
        "instant coffee": {
            "coffee",
            "instant coffee",
            "filter coffee",
            "ground coffee",
        },
        "filter coffee": {
            "coffee",
            "instant coffee",
            "filter coffee",
            "ground coffee",
        },
        "ground coffee": {
            "coffee",
            "instant coffee",
            "filter coffee",
            "ground coffee",
        },
        "milk": {
            "milk",
            "dairy",
        },
    }

    related = related_categories.get(
        original_category,
        set(),
    )

    if candidate_category in related:
        return 3

    return 4


def _infer_original_category(
    product_candidates: list[dict],
) -> str:
    """
    Try to get the category of the failed original product
    from an exact retrieval candidate.
    """

    for candidate in product_candidates:
        exact_score = candidate.get("exact_score")

        try:
            if (
                exact_score is not None
                and float(exact_score) >= 0.8
            ):
                return _normalize(
                    candidate.get("category")
                )
        except (TypeError, ValueError):
            pass

    return ""


# ============================================================
# FILTER SUBSTITUTE CANDIDATES
# ============================================================

def _filter_substitute_candidates(
    product_candidates: list[dict],
    original_product: str,
    attempted_product_ids: list[str] | None = None,
    preferred_brand: str | None = None,
) -> list[dict]:

    attempted_product_ids = (
        attempted_product_ids or []
    )

    attempted_ids = {
        _normalize(product_id)
        for product_id in attempted_product_ids
        if product_id
    }

    original_category = _infer_original_category(
        product_candidates
    )

    filtered = []

    for candidate in product_candidates:

        candidate_id = _get_product_id(candidate)

        # Already attempted.
        if (
            candidate_id
            and candidate_id in attempted_ids
        ):
            continue

        # Never use the failed exact product as its own
        # substitute.
        if _is_same_product(
            candidate,
            original_product,
        ):
            continue

        # Invalid candidate.
        if not _get_product_name(candidate):
            continue

        relationship = _candidate_relationship(
            candidate,
            original_category=original_category,
            preferred_brand=preferred_brand,
        )

        # 4 = unrelated.
        if relationship >= 4:
            continue

        filtered.append({
            **candidate,
            "substitution_relationship": relationship,
        })

    return filtered


# ============================================================
# RANK CANDIDATES
# ============================================================

def _rank_candidates(
    product_candidates: list[dict],
) -> list[dict]:

    return sorted(
        product_candidates,
        key=lambda candidate: (
            candidate.get(
                "substitution_relationship",
                4,
            ),

            -float(
                candidate.get(
                    "relevance_score",
                    0,
                )
                or 0
            ),

            -float(
                candidate.get(
                    "rrf_score",
                    0,
                )
                or 0
            ),
        ),
    )


# ============================================================
# DECIDE WHETHER TO SUBSTITUTE
# ============================================================

def decide_substitution(
    user_query: str,
    original_product: str,
    product_candidates: list[dict],
    shopping_goal: dict,
    personalized_preferences: dict,
    rejected_offers: list[dict] | None = None,
    attempted_product_ids: list[str] | None = None,
) -> dict:

    rejected_offers = rejected_offers or []
    attempted_product_ids = (
        attempted_product_ids or []
    )

    # Explicit exact-only request.
    if _is_exact_only_request(user_query):
        return {
            "substitution_requested": False,
            "substitution_reasoning": (
                "The customer requested the exact "
                "product and does not allow substitution."
            ),
            "reasoning": (
                "The customer requested the exact "
                "product and does not allow substitution."
            ),
            "candidates": [],
        }

    preferred_brand = (
        shopping_goal.get("preferred_brand")
    )

    filtered_candidates = (
        _filter_substitute_candidates(
            product_candidates=product_candidates,
            original_product=original_product,
            attempted_product_ids=attempted_product_ids,
            preferred_brand=preferred_brand,
        )
    )

    ranked_candidates = _rank_candidates(
        filtered_candidates
    )

    if not ranked_candidates:
        reasoning = (
            "No reasonable substitute candidates "
            "are available."
        )

        return {
            "substitution_requested": False,
            "substitution_reasoning": reasoning,
            "reasoning": reasoning,
            "candidates": [],
        }

    result = substitution_decision_llm.invoke(
        {
            "user_query": user_query,
            "original_product": original_product,
            "shopping_goal": shopping_goal,
            "personalized_preferences": (
                personalized_preferences
            ),
            "product_candidates": ranked_candidates,
            "rejected_offers": rejected_offers,
        }
    )

    return {
        "substitution_requested": (
            result.should_substitute
        ),
        "substitution_reasoning": result.reasoning,
        "reasoning": result.reasoning,
        "candidates": ranked_candidates,
    }


# ============================================================
# SELECT SUBSTITUTE
# ============================================================

def select_substitute(
    user_query: str,
    original_product: str,
    product_candidates: list[dict],
    shopping_goal: dict,
    personalized_preferences: dict,
    rejected_offers: list[dict] | None = None,
    attempted_product_ids: list[str] | None = None,
) -> dict:

    rejected_offers = rejected_offers or []
    attempted_product_ids = (
        attempted_product_ids or []
    )

    preferred_brand = (
        shopping_goal.get("preferred_brand")
    )

    filtered_candidates = (
        _filter_substitute_candidates(
            product_candidates=product_candidates,
            original_product=original_product,
            attempted_product_ids=attempted_product_ids,
            preferred_brand=preferred_brand,
        )
    )

    ranked_candidates = _rank_candidates(
        filtered_candidates
    )

    if not ranked_candidates:
        reasoning = (
            "No valid substitute remains "
            "after filtering."
        )

        return {
            "selected_substitute": None,
            "substitution_reasoning": reasoning,
            "reasoning": reasoning,
        }

    result = substitute_selector_llm.invoke(
        {
            "user_query": user_query,
            "original_product": original_product,
            "shopping_goal": shopping_goal,
            "personalized_preferences": (
                personalized_preferences
            ),
            "product_candidates": ranked_candidates,
            "rejected_offers": rejected_offers,
        }
    )

    selected_substitute = None

    if result.selected_product_index is not None:

        index = result.selected_product_index

        if (
            0 <= index
            < len(ranked_candidates)
        ):
            selected_substitute = (
                ranked_candidates[index]
            )

    # Deterministic fallback.
    if selected_substitute is None:
        selected_substitute = ranked_candidates[0]

    return {
        "selected_substitute": selected_substitute,
        "substitution_reasoning": result.reasoning,
        "reasoning": result.reasoning,
    }
