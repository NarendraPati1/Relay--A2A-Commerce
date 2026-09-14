from agents.buyer.llm import relevance_guard_llm


def check_relevance(
    user_query: str,
    shopping_goal: dict,
    product_candidates: list[dict],
):
    relevant = []
    rejected = []

    for candidate in product_candidates:
        result = relevance_guard_llm.invoke({
            "user_query": user_query,
            "shopping_goal": shopping_goal,
            "candidate": candidate,
        })

        item = {
            **candidate,
            "relevance_score": result.relevance_score,
            "relevance_reason": result.reasoning,
        }

        if result.is_relevant:
            relevant.append(item)
        else:
            rejected.append(item)

    return relevant, rejected