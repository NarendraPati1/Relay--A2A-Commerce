from agents.buyer.llm import (
    substitution_decision_llm,
    substitute_selector_llm,
)


def _norm(value) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _exact_only(query: str) -> bool:
    q = _norm(query)
    phrases = (
        "no substitute", "no substitutes", "do not substitute",
        "don't substitute", "dont substitute", "exact product",
        "exact item", "only this product", "nothing else",
    )
    return any(p in q for p in phrases)


def _id(candidate: dict) -> str:
    return _norm(candidate.get("product_id") or candidate.get("id"))


def _name(candidate: dict) -> str:
    return _norm(candidate.get("product_name") or candidate.get("name"))


def _same_product(candidate: dict, original_product: str) -> bool:
    cid = _id(candidate)
    name = _name(candidate)
    original = _norm(original_product)

    if not name:
        return True

    if cid and original and cid == original:
        return True

    if name == original:
        return True

    # If the original query is a strong substring of the candidate name,
    # treat it as the same family rather than a substitute.
    if original and len(original) >= 4 and original in name:
        return True

    return False


def _rank_candidates(candidates: list[dict]) -> list[dict]:
    """
    Do not hardcode category synonyms here.
    Semantic relationship is decided by the LLM.
    We only use retrieval/relevance scores as weak ranking signals.
    """
    return sorted(
        candidates,
        key=lambda c: (
            -float(c.get("relevance_score") or 0),
            -float(c.get("rrf_score") or 0),
            -float(c.get("vector_score") or 0),
        ),
    )


def _filter_candidates(
    candidates: list[dict],
    original_product: str,
    attempted_ids: set[str],
):
    result = []

    for candidate in candidates:
        cid = _id(candidate)

        if cid and cid in attempted_ids:
            continue

        if _same_product(candidate, original_product):
            continue

        if not _name(candidate):
            continue

        result.append(candidate)

    return _rank_candidates(result)


def decide_substitution(
    user_query: str,
    original_product: str,
    product_candidates: list[dict],
    shopping_goal: dict,
    personalized_preferences: dict,
    rejected_offers: list[dict] | None = None,
    attempted_product_ids: list[str] | None = None,
):
    if _exact_only(user_query):
        return {
            "substitution_requested": False,
            "substitution_reasoning": "Customer explicitly disallowed substitution.",
            "candidates": [],
        }

    attempted = {_norm(x) for x in (attempted_product_ids or [])}
    candidates = _filter_candidates(
        product_candidates,
        original_product,
        attempted,
    )

    if not candidates:
        return {
            "substitution_requested": False,
            "substitution_reasoning": "No untried substitute candidates are available.",
            "candidates": [],
        }

    if all(float(candidate.get("relevance_score") or 0) <= 0 for candidate in candidates):
        return {
            "substitution_requested": False,
            "substitution_reasoning": "No catalog candidate is related to the requested product.",
            "candidates": [],
        }

    try:
        result = substitution_decision_llm.invoke({
            "user_query": user_query,
            "original_product": original_product,
            "shopping_goal": shopping_goal,
            "product_candidates": candidates,
            "rejected_offers": rejected_offers or [],
        })
    except Exception:
        # A substitution is optional.  A provider refusing malformed JSON must
        # never make a completed offer comparison fail after the cart has
        # already been evaluated.
        return {
            "substitution_requested": False,
            "substitution_reasoning": "No substitution was proposed because the original request could not be verified.",
            "candidates": candidates,
        }

    return {
        "substitution_requested": result.should_substitute,
        "substitution_reasoning": result.reasoning,
        "candidates": candidates,
    }


def select_substitute(
    user_query: str,
    original_product: str,
    product_candidates: list[dict],
    shopping_goal: dict,
    personalized_preferences: dict,
    rejected_offers: list[dict] | None = None,
    attempted_product_ids: list[str] | None = None,
):
    attempted = {_norm(x) for x in (attempted_product_ids or [])}

    candidates = _filter_candidates(
        product_candidates,
        original_product,
        attempted,
    )

    if not candidates:
        return {
            "selected_substitute": None,
            "substitution_reasoning": "No valid untried substitute remains.",
        }

    try:
        result = substitute_selector_llm.invoke({
            "user_query": user_query,
            "original_product": original_product,
            "shopping_goal": shopping_goal,
            "personalized_preferences": personalized_preferences,
            "product_candidates": candidates,
            "rejected_offers": rejected_offers or [],
        })
    except Exception:
        return {
            "selected_substitute": None,
            "substitution_reasoning": "No alternative could be safely selected.",
        }

    selected = None
    if result.selected_product_index is not None:
        idx = result.selected_product_index
        if 0 <= idx < len(candidates):
            selected = candidates[idx]

    return {
        "selected_substitute": selected,
        "substitution_reasoning": result.reasoning,
    }
