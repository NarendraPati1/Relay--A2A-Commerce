from retrieval.vector_store import product_vector_store
from data.products import PRODUCTS
from retrieval.reranker import product_reranker


RRF_K = 60


def exact_search(query: str):
    query = query.lower().strip()

    results = []

    for product in PRODUCTS:
        name = product["name"].lower()
        brand = product["brand"].lower()
        category = product["category"].lower()

        score = 0.0

        if query == name:
            score = 1.0
        elif query == brand:
            score = 0.95
        elif query == category:
            score = 0.90
        elif query in name:
            score = 0.85
        elif query in brand:
            score = 0.80
        elif query in category:
            score = 0.75

        if score > 0:
            results.append({
                "product": product,
                "exact_score": score,
            })

    # Strongest exact match first
    results.sort(
        key=lambda x: x["exact_score"],
        reverse=True,
    )

    return results


def reciprocal_rank_fusion(
    exact_results: list[dict],
    vector_results: list[dict],
    k: int = RRF_K,
):
    fused = {}

    # -------------------------------------------------
    # Exact-search ranking
    # -------------------------------------------------

    for rank, result in enumerate(exact_results, start=1):

        product = result["product"]
        product_id = product["id"]

        if product_id not in fused:
            fused[product_id] = {
                "product": product,
                "exact_score": result["exact_score"],
                "vector_score": 0.0,
                "rrf_score": 0.0,
            }

        fused[product_id]["rrf_score"] += 1 / (k + rank)

    # -------------------------------------------------
    # Vector-search ranking
    # -------------------------------------------------

    for rank, result in enumerate(vector_results, start=1):

        product = result["product"]
        product_id = product["id"]

        if product_id not in fused:
            fused[product_id] = {
                "product": product,
                "exact_score": 0.0,
                "vector_score": result["vector_score"],
                "rrf_score": 0.0,
            }
        else:
            fused[product_id]["vector_score"] = (
                result["vector_score"]
            )

        fused[product_id]["rrf_score"] += 1 / (k + rank)

    # -------------------------------------------------
    # Sort by RRF
    # -------------------------------------------------

    results = list(fused.values())

    results.sort(
        key=lambda x: x["rrf_score"],
        reverse=True,
    )

    for result in results:
        result["rrf_score"] = round(
            result["rrf_score"],
            6,
        )

    return results


def search_products(query: str, top_k: int = 5):

    # 1. Exact retrieval
    exact_results = exact_search(query)

    # 2. Semantic retrieval
    candidate_limit = max(top_k * 3, top_k)
    vector_results = product_vector_store.search(
        query,
        top_k=candidate_limit,
    )

    # 3. RRF fusion
    fused_results = reciprocal_rank_fusion(
        exact_results,
        vector_results,
    )

    # Rerank only the small first-stage candidate set. It stays disabled until
    # the corresponding local weights have been provisioned.
    fused_results = product_reranker.rerank(
        query, fused_results[:candidate_limit]
    )

    # 4. Return top candidates
    candidates = []

    for result in fused_results[:top_k]:

        candidates.append({
            "product": result["product"],
            "exact_score": round(
                result["exact_score"],
                3,
            ),
            "vector_score": round(
                result["vector_score"],
                3,
            ),
            "rrf_score": result["rrf_score"],
        })

    return {
        "query": query,
        "candidates": candidates,
    }
