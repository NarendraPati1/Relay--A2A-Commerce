from agents.buyer.llm import relevance_guard_llm


def _words(value: str) -> set[str]:
    def normalize(word: str) -> str:
        """Normalize superficial plural forms without changing product terms."""
        word = word.lower().strip(".,;:!?()[]{}\"'")
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
        return word

    return {
        normalized
        for word in str(value or "").lower().replace("-", " ").split()
        if (normalized := normalize(word))
        if len(normalized) > 2
        and normalized not in {"want", "need", "with", "that", "this"}
    }


def _deterministic_relevance(
    shopping_goal: dict,
    candidate: dict,
) -> tuple[bool, str] | None:
    """Resolve obvious catalog matches without spending a model call."""
    query_words = _words(shopping_goal.get("product", ""))
    candidate_text = " ".join(str(candidate.get(field, "")) for field in (
        "name", "description", "category", "brand", "pack_size",
    )).lower()
    candidate_words = _words(candidate_text)
    # A pack size is product metadata.  Include generic package concepts so a
    # request such as "Nescafe Classic 100g packs" is not rejected merely
    # because catalogue values store "100g" rather than the word "pack".
    # This is intentionally product-agnostic and does not alter category
    # matching for broad requests such as "milk".
    if candidate.get("pack_size"):
        candidate_words.update({"pack", "package"})
    category_words = _words(candidate.get("category", ""))
    brand_words = _words(candidate.get("brand", ""))

    # A single generic product term should match the catalogue taxonomy (or an
    # explicit brand), not merely a coincidental word in another product name.
    # This prevents a product such as a "Dairy Milk" chocolate bar from
    # matching a generic request for milk, without encoding category names.
    if len(query_words) == 1 and not (
        query_words <= category_words or query_words <= brand_words
    ):
        return False, "Candidate taxonomy does not match the requested product."

    if len(query_words) > 1 and not query_words <= candidate_words:
        return False, "Candidate does not match the requested product category."

    for constraint in shopping_goal.get("constraints") or []:
        constraint_text = str(constraint).lower().strip()
        if any(term in constraint_text for term in (
            "cheap", "lowest", "best value", "discount", "deal", "price",
        )):
            # These are optimization preferences, not product attributes.
            continue
        # Positive product attributes must be evidenced in catalog metadata.
        if constraint_text and not any(
            negation in constraint_text
            for negation in ("avoid ", "exclude ", "not ", "no ")
        ) and constraint_text not in candidate_text:
            return False, f"Catalog metadata does not support constraint: {constraint}."

    if query_words:
        return True, "Direct catalog category/name match."
    return None


def check_relevance(
    user_query: str,
    shopping_goal: dict,
    product_candidates: list[dict],
):
    relevant = []
    rejected = []

    for candidate in product_candidates:
        deterministic = _deterministic_relevance(shopping_goal, candidate)
        if deterministic is not None:
            is_relevant, reasoning = deterministic
            relevance_score = 1.0 if is_relevant else 0.0
        else:
            result = relevance_guard_llm.invoke({
                "user_query": user_query,
                "shopping_goal": shopping_goal,
                "candidate": candidate,
            })
            is_relevant = result.is_relevant
            relevance_score = result.relevance_score
            reasoning = result.reasoning

        item = {
            **candidate,
            "relevance_score": relevance_score,
            "relevance_reason": reasoning,
        }

        if is_relevant:
            relevant.append(item)
        else:
            rejected.append(item)

    return relevant, rejected
